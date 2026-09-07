"""Validación documental de fase 4 en una copia aislada; nunca aprueba hechos.

Ejemplos (desde el proyecto, con scripts/dev-python.ps1):
  scripts/validate_history.py prepare --reference output/validation-f4/reference-proposal.json
  scripts/validate_history.py run --subset development
  scripts/validate_history.py run --subset holdout
  scripts/validate_history.py report

La referencia usa schema_version=1, collection_ids y cases. Cada caso requiere
id, title, description, holdout, request_source={source_id, refs:[{page,
line_start,line_end,quote}]} y expected_source_groups=[{id,source_ids,essential,
rationale}]. También se aceptan las cuatro coordenadas directamente en request_source.
Cada grupo admite cualquiera de sus fuentes equivalentes. Un grupo esencial vacío
es inválido: un documento ausente se describe en expected_limitations.

prepare congela las referencias, copia SQLite mediante backup y elimina de la copia
las fuentes ajenas a las colecciones seleccionadas, vínculos y ejecuciones vivas.
Los originales se leen y verifican por SHA desde su ubicación inmutable; solo el
PDF de cada petición se copia al expediente QA. Una pregunta reproducida en DOCX
produce un PDF derivado QA y conserva aparte su cita literal en el DOCX.

run llama al SourceService y LangGraph de la aplicación con el evaluador OpenAI
existente. Una ejecución correcta se reutiliza; los errores se pueden reintentar.
Para repetir resultados correctos tras cambiar el motor, preparar otro --output-dir.
No se prueba aquí la identificación automática de peticiones ni la aprobación humana.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import textwrap
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pymupdf

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import Identification, Page, Request, SourceRef, validate_identification
from pqrs_claro.source_assessment import OpenAISourceAssessor
from pqrs_claro.source_library import SourceLibrary, digest
from pqrs_claro.source_service import SourceService
from pqrs_claro.storage import CaseStore, now


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def output_path(value):
    path = Path(value).resolve()
    allowed = (ROOT / "output").resolve()
    if not path.is_relative_to(allowed) or path == allowed:
        raise ValueError("La validación debe usar un subdirectorio de output del proyecto.")
    return path


def source_refs(request_source):
    return request_source.get("refs") or [
        {key: request_source[key] for key in ("page", "line_start", "line_end", "quote")}
    ]


def validate_reference(reference):
    if reference.get("schema_version") != 1:
        raise ValueError("schema_version debe ser 1.")
    collections = reference.get("collection_ids", [])
    if not collections or len(set(collections)) != len(collections):
        raise ValueError("Indica colecciones únicas para esta validación.")
    cases = reference.get("cases", [])
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Indica casos con identificadores únicos.")
    for case in cases:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", case["id"]):
            raise ValueError("Identificador de muestra no válido.")
        if not isinstance(case.get("holdout"), bool):
            raise ValueError("Cada muestra debe indicar holdout true o false.")
        if not case.get("title", "").strip() or not case.get("description", "").strip():
            raise ValueError("Cada muestra necesita título y descripción.")
        source_refs(case["request_source"])
        groups = case.get("expected_source_groups", [])
        if len({group["id"] for group in groups}) != len(groups):
            raise ValueError("Los grupos esperados deben tener identificadores únicos.")
        for group in groups:
            if group.get("essential", True) and not group.get("source_ids"):
                raise ValueError("Un grupo esencial necesita fuentes concretas existentes.")


class SnapshotLibrary(SourceLibrary):
    """Metadatos y escrituras QA; originales existentes solo como entradas de lectura."""

    def __init__(self, data_dir, originals):
        super().__init__(data_dir, PDFExtractor())
        self.root = Path(originals).resolve(strict=True)
        with self.connect() as connection:
            rows = connection.execute("SELECT body FROM sources").fetchall()
        for row in rows:
            source = json.loads(row[0])
            if not re.fullmatch(r"[a-f0-9]{32}", source["id"]):
                raise ValueError("El snapshot contiene un identificador inseguro.")
            candidate = self.root / source["id"] / (
                "original" + Path(source["filename"]).suffix.lower()
            )
            if not candidate.resolve().is_relative_to(self.root):
                raise ValueError("El original queda fuera de la biblioteca declarada.")

    def add(self, *args, **kwargs):
        raise ValueError("El harness no incorpora ni reemplaza originales compartidos.")


def copy_snapshot(source_data, qa_data, collections):
    qa_data.mkdir(parents=True, exist_ok=False)
    target = qa_data / "biblioteca.sqlite"
    original = (source_data / "biblioteca.sqlite").resolve(strict=True)
    with sqlite3.connect(original.as_uri() + "?mode=ro", uri=True) as reader:
        with sqlite3.connect(target) as writer:
            reader.backup(writer)
    with sqlite3.connect(target) as connection:
        sources = connection.execute("SELECT id,body FROM sources").fetchall()
        kept = {
            source_id for source_id, body in sources
            if json.loads(body).get("collection_id") in collections
            and json.loads(body).get("case_id") is None
        }
        if not kept:
            raise ValueError("La colección seleccionada no contiene fuentes en el snapshot.")
        connection.executemany(
            "DELETE FROM sources WHERE id=?", [(item, ) for item, _ in sources if item not in kept]
        )
        connection.execute("DELETE FROM source_runs")
        connection.execute("DELETE FROM case_source_collections")
        connection.execute("DELETE FROM source_reviews WHERE id NOT IN (SELECT id FROM sources)")
        connection.execute(
            "DELETE FROM source_relationships WHERE source_id NOT IN (SELECT id FROM sources) "
            "OR target_id NOT IN (SELECT id FROM sources)"
        )
        for collection_id, in connection.execute("SELECT id FROM source_collections").fetchall():
            if collection_id not in collections:
                connection.execute("DELETE FROM source_collections WHERE id=?", (collection_id,))
        available = {row[0] for row in connection.execute("SELECT id FROM source_collections")}
        if available != set(collections):
            raise ValueError("No existen todas las colecciones solicitadas.")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Falló la integridad SQLite del snapshot.")
    return {"source_count": len(kept), "source_database": str(original)}


def check_quote(library, citation, case_id=None):
    detail = library.get(citation["source_id"], case_id)
    return (
        quote_matches_pages(detail["pages"], citation)
        and citation.get("version", detail["source"]["version"]) == detail["source"]["version"]
    )


def quote_matches_pages(pages, citation):
    page = next(
        (item for item in pages if item["number"] == citation["page"]), None
    )
    if page is None:
        return False
    lines = page["text"].splitlines()
    first, last = citation["line_start"], citation["line_end"]
    return (
        1 <= first <= last <= len(lines)
        and "\n".join(lines[first - 1:last]) == citation["quote"]
    )


def request_original(origin, library, live_data):
    """Las peticiones vivas también se leen sin abrir conexiones que escriban en SQLite."""
    if origin.get("source_id"):
        detail = library.get(origin["source_id"])
        return library.original(origin["source_id"]), detail["pages"]
    case_id = origin.get("live_case_id", "")
    if not re.fullmatch(r"[a-f0-9]{32}", case_id):
        raise ValueError("El origen necesita source_id o live_case_id válido.")
    database = (live_data / "expedientes.sqlite").resolve(strict=True)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT body FROM cases WHERE id=?", (case_id,)).fetchone()
    if row is None:
        raise ValueError("La petición original no existe en el expediente de origen.")
    case = json.loads(row[0])
    original = (live_data / "files" / case_id / "original.pdf").resolve(strict=True)
    if not original.is_relative_to((live_data / "files").resolve()):
        raise ValueError("La petición original queda fuera de los expedientes declarados.")
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    if sha != case["sha256"] or sha != origin.get("original_sha256", sha):
        raise ValueError("El SHA de la petición original no coincide con la referencia.")
    return original, case["pages"]


def derived_pdf(sample):
    """PDF de trabajo visible, con citas reales cuya procedencia queda en el manifiesto."""
    font_file = Path("C:/Windows/Fonts/arial.ttf")
    font = pymupdf.Font(fontfile=str(font_file)) if font_file.is_file() else pymupdf.Font("cjk")
    lines = []
    for ref in source_refs(sample["request_source"]):
        for line in ref["quote"].splitlines():
            lines.extend(textwrap.wrap(line, width=150) or [""])
    with pymupdf.open() as document:
        for start in range(0, len(lines), 60):
            page = document.new_page(width=1100, height=1100)
            writer = pymupdf.TextWriter(page.rect)
            writer.append((30, 25), "COPIA DERIVADA QA: extractos reproducidos en un DOCX.",
                          font=font, fontsize=9)
            writer.append((30, 42), "No es la petición original ni una respuesta aprobada.",
                          font=font, fontsize=9)
            for index, line in enumerate(lines[start:start + 60]):
                size = min(10, 1035 / max(font.text_length(line, fontsize=1), 1))
                writer.append((30, 75 + index * 15), line, font=font, fontsize=size)
            writer.write_text(page)
        return document.tobytes()


def prepare(output, reference_path, settings):
    reference = read_json(reference_path)
    validate_reference(reference)
    frozen = output / "reference.json"
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if digest(read_json(frozen)) != digest(reference):
            raise ValueError(
                "La referencia cambió; prepara otra carpeta QA para conservar la prueba."
            )
        return read_json(manifest_path)
    output.mkdir(parents=True, exist_ok=True)
    qa_data = output / "data"
    facts = copy_snapshot(settings.data_dir, qa_data, reference["collection_ids"])
    write_json(frozen, reference)
    originals = (settings.data_dir / "library").resolve(strict=True)
    library, cases = SnapshotLibrary(qa_data, originals), CaseStore(qa_data)
    manifest = {
        "schema_version": 1, "created_at": now(), "reference_sha256": digest(reference),
        "originals_read_only_path": str(originals), "snapshot": facts,
        "mode": "real_source_graph_with_documentary_reference",
        "identification_tested": False, "institutional_approval": False, "cases": [],
    }
    for sample in reference["cases"]:
        origin = sample["request_source"]
        original, original_pages = request_original(origin, library, settings.data_dir)
        refs = source_refs(origin)
        for ref in refs:
            if not quote_matches_pages(original_pages, ref):
                raise ValueError(f"La cita de origen de {sample['id']} no coincide literalmente.")
        for group in sample.get("expected_source_groups", []):
            for source_id in group.get("source_ids", []):
                library.get(source_id)
            for evidence_ref in group.get("evidence_refs", []):
                if not check_quote(library, evidence_ref):
                    raise ValueError(
                        f"El sustento esperado de {sample['id']}/{group['id']} no es literal."
                    )
        derived = original.suffix.lower() != ".pdf"
        if derived:
            pdf = derived_pdf(sample)
            with pymupdf.open(stream=pdf, filetype="pdf") as document:
                pages = [Page(number=index + 1, text=page.get_text("text", sort=True).strip("\n"),
                              method="native", needs_review=False)
                         for index, page in enumerate(document)]
            case_refs = [SourceRef(page=page.number, line_start=1,
                                   line_end=len(page.text.splitlines()), quote=page.text)
                         for page in pages]
        else:
            pdf = original.read_bytes()
            pages = [Page.model_validate(page) for page in original_pages]
            case_refs = [SourceRef.model_validate(ref) for ref in refs]
        identification = Identification(
            subject=sample["title"],
            requests=[Request(id="P1", label=sample["id"], title=sample["title"],
                              description=sample["description"], source_refs=case_refs)],
            warnings=["Muestra QA documental; la aprobación institucional está pendiente."],
        )
        validate_identification(identification, pages)
        case = cases.create(f"QA {sample['id']} - copia documental.pdf", pdf)
        case = cases.update(
            case["id"], status="confirmed", mode="validation", confirmed_at=now(),
            pages=[page.model_dump() for page in pages],
            identification=identification.model_dump(), validation_origin=origin,
            event="Referencia documental preparada para fase 4; no es aprobación institucional.",
        )
        library.link_collections(case["id"], reference["collection_ids"])
        manifest["cases"].append({
            "id": sample["id"], "case_id": case["id"], "holdout": sample["holdout"],
            "original_sha256": case["sha256"], "derived_qa_pdf": derived,
            "request_origin_kind": sample.get("request_origin_kind")
                or ("reproduced_in_document" if derived else "source_pdf"),
        })
    write_json(manifest_path, manifest)
    return manifest


COMPACT_FIELDS = (
    "source_id", "chunk_id", "document_id", "version", "title", "filename", "category",
    "case_id", "collection_id", "page", "line_start", "line_end", "quote", "method",
    "needs_review", "location_kind", "extraction_status", "document_status",
    "verification_status", "review_status", "validity", "score", "matched_terms", "role",
    "reason", "identifier_conflicts", "office_numbers", "radicados",
)


def compact_chunk(chunk):
    return {key: chunk[key] for key in COMPACT_FIELDS if key in chunk}


def execution_info(settings, reference, subset, ids):
    """Registra configuración no secreta y código disponible al iniciar este proceso."""
    paths = [Path(__file__).resolve(), ROOT / "pyproject.toml"]
    paths.extend(sorted((ROOT / "src" / "pqrs_claro").glob("*.py")))
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in paths}
    dependencies = {}
    for package in ("langgraph", "langgraph-checkpoint-sqlite", "openai", "pydantic", "pymupdf"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = None
    service_source = (ROOT / "src" / "pqrs_claro" / "source_service.py").read_text("utf-8")
    analysis_version = re.search(r'"analysis_version"\s*:\s*(\d+)', service_source)
    return {
        "attempt_id": now().replace(":", "").replace(".", "") + "_" + uuid4().hex[:8],
        "started_at": now(), "status": "running", "subset": subset,
        "selected_ids": ids, "model": settings.model,
        "analysis_version": int(analysis_version.group(1)) if analysis_version else None,
        "reference_sha256": digest(reference), "git_head": head,
        "python_version": platform.python_version(), "dependencies": dependencies,
        "code_sha256": hashes, "code_snapshot_sha256": digest(hashes),
        "institutional_approval": False,
        "reproducibility_note": "Se conservan entradas y código identificado por SHA; "
            "una llamada al modelo no garantiza una salida idéntica en otra ejecución.",
    }


def archive_sample(output, attempt_dir, sample_id, *, previous=False):
    """Las copias anteriores nunca se sobrescriben entre intentos distintos."""
    destination = attempt_dir / "previous" if previous else attempt_dir
    for folder in ("calls", "results"):
        source = output / folder / f"{sample_id}.json"
        if source.is_file():
            target = destination / folder / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


class RecordingAssessor:
    def __init__(self, delegate, output, *, attempt_id=None, library=None):
        self.delegate, self.output = delegate, output
        self.sample_id = None
        self.attempt_id, self.library = attempt_id, library

    def assess(self, request, candidates):
        started = time.monotonic()
        run = self.library.latest_run(request["case_id"]) if self.library else None
        record = {"sample_id": self.sample_id, "started_at": now(),
                  "attempt_id": self.attempt_id, "model": getattr(self.delegate, "model", None),
                  "run_id": run["id"] if run else None,
                  "fingerprint": run["fingerprint"] if run else None,
                  "request": request, "candidates": [compact_chunk(c) for c in candidates]}
        path = self.output / "calls" / f"{self.sample_id}.json"
        write_json(path, record)
        try:
            result = self.delegate.assess(request, candidates)
            record["finding"] = {**result, "supports": [compact_chunk(c)
                                                       for c in result["supports"]]}
            return result
        except Exception as exc:
            # No registrar mensajes de proveedor que pudieran contener credenciales.
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            write_json(path, record)


def evaluate_result(sample, mapping, candidates, library, persistence):
    candidate_ids = {candidate["source_id"] for candidate in candidates}
    findings = mapping.get("results", [])
    supports = [support for finding in findings for support in finding.get("supports", [])]
    support_ids = {support["source_id"] for support in supports}
    groups = []
    for group in sample.get("expected_source_groups", []):
        expected = set(group.get("source_ids", []))
        groups.append({
            **group, "retrieved_ids": sorted(expected & candidate_ids),
            "selected_ids": sorted(expected & support_ids),
            "retrieval_passed": bool(expected & candidate_ids),
            "selected": bool(expected & support_ids),
        })
    quote_checks = [
        {"chunk_id": support["chunk_id"],
         "passed": check_quote(library, support, mapping["case_id"])}
        for support in supports
    ]
    quotes_ok = all(check["passed"] for check in quote_checks)
    essentials_ok = all(group["retrieval_passed"] for group in groups
                        if group.get("essential", True))
    technical = mapping["status"] == "ready" and quotes_ok and all(persistence.values())
    return {
        "sample_id": sample["id"], "title": sample["title"], "holdout": sample["holdout"],
        "checked_at": now(), "graph_status": mapping["status"],
        "technical_passed": technical, "essential_retrieval_passed": essentials_ok,
        "candidate_count": len(candidates), "support_count": len(supports),
        "groups": groups, "exact_quote_checks": quote_checks,
        "persistence": persistence, "semantic_review": "pending",
        "institutional_approval": False,
        "findings": [{**finding, "supports": [compact_chunk(c)
                                              for c in finding.get("supports", [])]}
                     for finding in findings],
        "error": mapping.get("error"),
        "expected_limitations": sample.get("expected_limitations", []),
        "forbidden_claims": sample.get("forbidden_claims", []),
    }


def persistence_checks(service, mapping, case_id, settings, cases, library):
    original = library.linked_collections(case_id)
    verifier = SourceService(settings, CaseStore(settings.data_dir), library)
    try:
        restored = verifier.get(case_id)
        persisted = restored["results"] == mapping["results"] and restored["id"] == mapping["id"]
        library.link_collections(case_id, [])
        unlinked_stale = verifier.get(case_id)["stale"]
    finally:
        library.link_collections(case_id, original)
        verifier.close()
    reattached = service.get(case_id)
    return {
        "reopened_results_identical": persisted,
        "unlinked_marks_stale": unlinked_stale,
        "restored_links_match_fingerprint": not reattached["stale"],
        "case_original_sha256_valid": bool(cases.original(case_id)),
    }


def run(output, subset, settings, ids=None):
    reference, manifest = read_json(output / "reference.json"), read_json(output / "manifest.json")
    if digest(reference) != manifest["reference_sha256"]:
        raise ValueError("La referencia congelada fue modificada.")
    settings = replace(settings, data_dir=output / "data")
    if not settings.api_key:
        raise ValueError(
            "No hay clave OpenAI configurada; no se sustituirá por un evaluador falso."
        )
    case_index = {case["id"]: case for case in manifest["cases"]}
    selected = [sample for sample in reference["cases"]
                if (subset == "all" or sample["holdout"] == (subset == "holdout"))
                and (not ids or sample["id"] in ids)]
    if not selected:
        raise ValueError("No hay muestras para esa selección.")
    execution = execution_info(settings, reference, subset, [sample["id"] for sample in selected])
    attempt_dir = output / "attempts" / execution["attempt_id"]
    write_json(attempt_dir / "execution.json", execution)
    library = SnapshotLibrary(settings.data_dir, manifest["originals_read_only_path"])
    library.recover()
    cases = CaseStore(settings.data_dir)
    assessor = RecordingAssessor(OpenAISourceAssessor(settings.api_key, settings.model), output,
                                 attempt_id=execution["attempt_id"], library=library)
    service = SourceService(settings, cases, library, assessor=assessor)
    finished_results = []
    try:
        for sample in selected:
            sample_id = sample["id"]
            assessor.sample_id = sample_id
            case_id = case_index[sample_id]["case_id"]
            started = time.monotonic()
            print(json.dumps({"event": "starting", "sample_id": sample_id}, ensure_ascii=False),
                  flush=True)
            try:
                archive_sample(output, attempt_dir, sample_id, previous=True)
                mapping = service.start(case_id, cases.get(case_id)["version"])
                while mapping["status"] == "running":
                    time.sleep(0.5)
                    mapping = library.latest_run(case_id)
                persisted = persistence_checks(service, mapping, case_id, settings, cases, library)
                call_path = output / "calls" / f"{sample_id}.json"
                call = read_json(call_path) if call_path.exists() else {}
                candidates = call.get("candidates", [])
                result = evaluate_result(sample, mapping, candidates, library, persisted)
                result.update(run_id=mapping["id"], fingerprint=mapping["fingerprint"],
                              source_call_attempt_id=call.get("attempt_id"),
                              model_called=call.get("attempt_id") == execution["attempt_id"])
            except Exception as exc:
                # No copiar textos arbitrarios de excepciones, cabeceras ni configuración.
                result = {
                    "sample_id": sample_id, "title": sample["title"],
                    "holdout": sample["holdout"], "checked_at": now(),
                    "graph_status": "error", "technical_passed": False,
                    "essential_retrieval_passed": False, "candidate_count": 0,
                    "support_count": 0, "groups": [], "findings": [],
                    "exact_quote_checks": [], "persistence": {},
                    "semantic_review": "pending", "institutional_approval": False,
                    "script_error_type": type(exc).__name__,
                    "error": "La muestra no completó su ejecución o comprobación técnica. "
                             "El tipo de error quedó registrado sin mensajes del proveedor.",
                    "expected_limitations": sample.get("expected_limitations", []),
                    "forbidden_claims": sample.get("forbidden_claims", []),
                }
            result.update(elapsed_seconds=round(time.monotonic() - started, 3),
                          model=settings.model, case_id=case_id,
                          attempt_id=execution["attempt_id"],
                          code_snapshot_sha256=execution["code_snapshot_sha256"])
            write_json(output / "results" / f"{sample_id}.json", result)
            archive_sample(output, attempt_dir, sample_id)
            finished_results.append(result)
            print(json.dumps({"event": "completed", "sample_id": sample_id,
                              "graph_status": result["graph_status"],
                              "technical_passed": result["technical_passed"],
                              "essential_retrieval_passed": result["essential_retrieval_passed"],
                              "elapsed_seconds": result["elapsed_seconds"]}), flush=True)
    finally:
        try:
            service.close()
        finally:
            execution.update(
                finished_at=now(), completed_count=len(finished_results),
                status="completed" if len(finished_results) == len(selected) else "interrupted",
                technical_error_count=sum(not result["technical_passed"]
                                          for result in finished_results),
            )
            write_json(attempt_dir / "execution.json", execution)
            summary = report(output)
    return summary


def report(output):
    reference = read_json(output / "reference.json")
    results = [read_json(path) for path in sorted((output / "results").glob("*.json"))]
    summary = {
        "generated_at": now(), "sample_size": len(reference["cases"]),
        "completed": len(results), "technical_passed": sum(r["technical_passed"] for r in results),
        "essential_retrieval_passed": sum(r["essential_retrieval_passed"] for r in results),
        "semantic_review": "pending", "institutional_approval": False,
        "results": [{key: result[key] for key in
                     ("sample_id", "title", "holdout", "graph_status", "technical_passed",
                      "essential_retrieval_passed", "support_count", "elapsed_seconds")}
                    for result in results],
    }
    write_json(output / "technical-summary.json", summary)
    lines = ["# Validación técnica documental de fase 4", "",
             "La aprobación institucional y la revisión semántica están pendientes.",
             "Esta prueba comienza con solicitudes documentales preparadas; no valida la "
             "identificación automática ni implica aprobación humana del expediente.", "",
             "| Muestra | Reserva | Grafo | Comprobaciones técnicas | Fuentes esenciales |",
             "|---|---|---|---|---|"]
    for result in results:
        lines.append(f"| {result['sample_id']} | {result['holdout']} | {result['graph_status']} | "
                     f"{result['technical_passed']} | {result['essential_retrieval_passed']} |")
    lines += ["", "Cada results/*.json conserva citas, faltantes, grupos recuperados y revisión "
              "de persistencia. calls/*.json conserva únicamente los candidatos enviados "
              "a la evaluación y su duración.", ""]
    (output / "TECHNICAL-REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["prepare", "run", "report"])
    parser.add_argument("--output-dir", default=str(ROOT / "output" / "validation-f4"))
    parser.add_argument("--reference", type=Path)
    parser.add_argument(
        "--subset", choices=["development", "holdout", "all"], default="development"
    )
    parser.add_argument("--ids", nargs="+")
    args = parser.parse_args()
    output = output_path(args.output_dir)
    settings = Settings.load()
    if args.command == "prepare":
        if args.reference is None:
            parser.error("prepare requiere --reference.")
        result = prepare(output, args.reference, settings)
        print(json.dumps({"prepared": len(result["cases"]), "snapshot": result["snapshot"],
                          "output": str(output)}, ensure_ascii=False))
    elif args.command == "run":
        result = run(output, args.subset, settings, args.ids)
        print(json.dumps({key: value for key, value in result.items() if key != "results"}))
    else:
        print(json.dumps(report(output), ensure_ascii=False))


if __name__ == "__main__":
    main()
