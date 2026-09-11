"""Reevalúa una petición exacta en una copia QA, sin aprobar hechos ni escribir en vivo.

Ejemplos (desde el proyecto, usando scripts/dev-python.ps1):
  scripts/validate_pending_workflow.py prepare
  scripts/validate_pending_workflow.py run --through sources
  scripts/validate_pending_workflow.py rematerialize --from-attempt ID_DEL_INTENTO
  scripts/validate_pending_workflow.py run --through reviews
  scripts/validate_pending_workflow.py report
  scripts/validate_pending_workflow.py integrity

prepare no llama a la IA. Congela el caso, el último mapa, las bases de negocio
y sus huellas; crea copias SQLite mediante backup de conexiones mode=ro y copia
el PDF de la petición y el modelo/caché semánticos. Los originales de las fuentes
son entradas de lectura del harness y nunca se incorporan ni reemplazan.

run usa SourceService, DraftService y ReviewService reales con data_dir QA.
Los resultados previos compatibles se reutilizan; cada intento conserva su
manifiesto, llamadas, progreso y resultados. No se crean confirmaciones humanas,
aprobaciones, oficios, firmas ni envíos. La revisión semántica manual se registra
por separado: una evaluación de IA no equivale a esa revisión.
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
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.draft_engine import OpenAIDraftEngine
from pqrs_claro.draft_service import DraftService
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.review_engine import OpenAIReviewEngine
from pqrs_claro.review_service import ReviewService
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.source_library import SourceLibrary, digest
from pqrs_claro.source_semantic import MODEL_FILE, MODEL_KEY, MODEL_REVISION
from pqrs_claro.source_service import SourceService
from pqrs_claro.source_verifications import SourceVerificationStore
from pqrs_claro.storage import CaseStore, now

DEFAULT_CASE = "8f6c723a34654c9a87ab5ad262996609"
DEFAULT_OUTPUT = ROOT / "output" / "qa" / "pending-verifications-20260909"
BUSINESS_DATABASES = (
    "expedientes.sqlite", "biblioteca.sqlite", "borradores.sqlite",
    "revisiones.sqlite", "oficios.sqlite", "comprobaciones.sqlite",
)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def file_sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def qa_path(value):
    path = Path(value).resolve()
    allowed = (ROOT / "output").resolve()
    if path == allowed or not path.is_relative_to(allowed):
        raise ValueError("La copia QA debe estar en un subdirectorio de output del proyecto.")
    return path


def read_connection(path):
    return sqlite3.connect(Path(path).resolve(strict=True).as_uri() + "?mode=ro", uri=True)


def database_snapshot(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError(f"Se conserva el snapshot existente: {target.name}.")
    with read_connection(source) as reader, sqlite3.connect(target) as writer:
        reader.backup(writer)
        if writer.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Falló la integridad SQLite de la copia.")


def database_fingerprint(path):
    """Huella lógica estable, independiente del WAL y del orden físico de páginas."""
    if not path.is_file():
        return {"exists": False}
    tables = {}
    with read_connection(path) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )]
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            rows, count = hashlib.sha256(), 0
            # Las tablas de negocio usan rowid. Se mantiene ese orden al congelar la base.
            for row in connection.execute(f"SELECT * FROM {quoted} ORDER BY rowid"):
                serializable = [
                    {"bytes_sha256": hashlib.sha256(value).hexdigest()}
                    if isinstance(value, bytes) else value for value in row
                ]
                rows.update(json.dumps(serializable, ensure_ascii=False).encode("utf-8"))
                rows.update(b"\n")
                count += 1
            tables[name] = {"rows": count, "sha256": rows.hexdigest()}
    return {"exists": True, "tables": tables, "sha256": digest(tables)}


def live_fingerprint(data, case_id):
    databases = {name: database_fingerprint(data / name) for name in BUSINESS_DATABASES}
    original = data / "files" / case_id / "original.pdf"
    return {
        "databases": databases,
        "petition_original_sha256": file_sha(original),
    }


def code_snapshot():
    paths = sorted((ROOT / "src" / "pqrs_claro").rglob("*.py"))
    paths += [ROOT / "pyproject.toml", ROOT / "uv.lock", Path(__file__).resolve()]
    return {str(path.relative_to(ROOT)).replace("\\", "/"): file_sha(path) for path in paths}


def log_event(output, event, **values):
    record = {"at": now(), "event": event, **values}
    with (output / "progress.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), flush=True)


class SnapshotLibrary(SourceLibrary):
    """Bases QA y originales compartidos que el harness solo puede consultar."""

    def __init__(self, data_dir, originals):
        super().__init__(data_dir, PDFExtractor())
        self.root = Path(originals).resolve(strict=True)
        with self.connect() as connection:
            rows = connection.execute("SELECT body FROM sources").fetchall()
        for body, in rows:
            source = json.loads(body)
            if not re.fullmatch(r"[a-f0-9]{32}", source["id"]):
                raise ValueError("El snapshot contiene un identificador inseguro.")
            candidate = self.root / source["id"] / (
                "original" + Path(source["filename"]).suffix.lower()
            )
            if not candidate.resolve().is_relative_to(self.root):
                raise ValueError("Un original queda fuera de la biblioteca de lectura.")

    def add(self, *args, **kwargs):
        raise ValueError("El harness no incorpora ni reemplaza originales compartidos.")


def prepare(output, live_data, case_id, baseline_path):
    if (output / "manifest.json").exists() or (output / "data").exists():
        raise ValueError("La copia ya existe. Use run/report o un output-dir nuevo.")
    live_data = live_data.resolve(strict=True)
    if live_data.is_relative_to(output) or output.is_relative_to(live_data):
        raise ValueError("El origen vivo y la copia QA deben estar separados.")
    if not re.fullmatch(r"[a-f0-9]{32}", case_id):
        raise ValueError("El identificador de petición no es válido.")
    output.mkdir(parents=True, exist_ok=True)
    initial = live_fingerprint(live_data, case_id)
    write_json(output / "live-integrity-before.json", initial)
    backup = output / "baseline" / "databases"
    for name in BUSINESS_DATABASES:
        if (live_data / name).is_file():
            database_snapshot(live_data / name, backup / name)
    with read_connection(backup / "expedientes.sqlite") as connection:
        row = connection.execute("SELECT body FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        raise ValueError("El expediente no existe en el origen.")
    case = json.loads(row[0])
    if case["status"] != "confirmed":
        raise ValueError("El harness requiere solicitudes confirmadas.")
    if case["sha256"] != initial["petition_original_sha256"]:
        raise ValueError("La huella del PDF original no coincide con el expediente.")
    with read_connection(backup / "biblioteca.sqlite") as connection:
        collections = sorted(row[0] for row in connection.execute(
            "SELECT collection_id FROM case_source_collections WHERE case_id=?", (case_id,)
        ))
        latest = connection.execute(
            "SELECT body FROM source_runs WHERE case_id=? ORDER BY rowid DESC LIMIT 1",
            (case_id,),
        ).fetchone()
    if not latest:
        raise ValueError("No existe un mapa vivo previo para comparar.")
    live_map = json.loads(latest[0])
    expected_baseline = read_json(baseline_path) if baseline_path else live_map
    if expected_baseline.get("id") != live_map.get("id"):
        raise ValueError("El mapa vivo cambió respecto a la línea de base declarada.")
    write_json(output / "baseline" / "case.json", case)
    write_json(output / "baseline" / "source-run.json", live_map)
    data = output / "data"
    data.mkdir()
    for name in ("expedientes.sqlite", "biblioteca.sqlite"):
        database_snapshot(backup / name, data / name)
    with sqlite3.connect(data / "expedientes.sqlite") as connection:
        connection.execute("DELETE FROM cases WHERE id<>?", (case_id,))
        connection.execute("DELETE FROM revisions WHERE case_id<>?", (case_id,))
    with sqlite3.connect(data / "biblioteca.sqlite") as connection:
        sources = connection.execute("SELECT id,body FROM sources").fetchall()
        removed = []
        for source_id, body in sources:
            source = json.loads(body)
            if source.get("case_id") not in (None, case_id) or (
                source.get("collection_id") and source["collection_id"] not in collections
            ):
                removed.append((source_id,))
        connection.executemany("DELETE FROM sources WHERE id=?", removed)
        connection.execute("DELETE FROM source_runs")
        connection.execute("DELETE FROM case_source_collections WHERE case_id<>?", (case_id,))
        connection.execute("DELETE FROM source_reviews WHERE id NOT IN (SELECT id FROM sources)")
        connection.execute(
            "DELETE FROM source_relationships WHERE source_id NOT IN (SELECT id FROM sources) "
            "OR target_id NOT IN (SELECT id FROM sources)"
        )
        for collection_id, in connection.execute("SELECT id FROM source_collections").fetchall():
            if collection_id not in collections:
                connection.execute("DELETE FROM source_collections WHERE id=?", (collection_id,))
    petition = data / "files" / case_id / "original.pdf"
    petition.parent.mkdir(parents=True)
    shutil.copy2(live_data / "files" / case_id / "original.pdf", petition)
    semantic = data / "semantic"
    semantic.mkdir()
    cache = live_data / "semantic" / "embeddings.sqlite"
    if cache.is_file():
        database_snapshot(cache, semantic / "embeddings.sqlite")
    model = live_data / "semantic" / "models" / MODEL_REVISION
    if not (model / MODEL_FILE).is_file():
        raise ValueError("No está instalado el modelo semántico de la línea de base.")
    shutil.copytree(model, semantic / "models" / MODEL_REVISION)
    manifest = {
        "schema_version": 1, "created_at": now(), "case_id": case_id,
        "case_version": case["version"], "request_count": case["request_count"],
        "case_sha256": digest(case), "petition_original_sha256": case["sha256"],
        "live_data_read_only": str(live_data), "qa_data": str(data),
        "originals_read_only_path": str(live_data / "library"),
        "collection_ids": collections, "baseline_source_run_id": live_map["id"],
        "baseline_source_run_sha256": digest(live_map),
        "semantic_model": MODEL_KEY, "semantic_cache_copied": cache.is_file(),
        "manual_review": "pending", "institutional_approval": False,
        "code_snapshot_at_prepare": code_snapshot(),
    }
    write_json(output / "manifest.json", manifest)
    unchanged = verify_integrity(output)
    report(output)
    log_event(output, "prepared", case_id=case_id, case_version=case["version"],
              request_count=case["request_count"], collections=collections,
              live_unchanged=unchanged["live_unchanged"], data_dir=str(data))


def verify_integrity(output):
    manifest = read_json(output / "manifest.json")
    baseline = read_json(output / "live-integrity-before.json")
    after = live_fingerprint(Path(manifest["live_data_read_only"]), manifest["case_id"])
    differences = []
    for key, before in baseline["databases"].items():
        if before != after["databases"].get(key):
            differences.append(key)
    if baseline["petition_original_sha256"] != after["petition_original_sha256"]:
        differences.append("petition_original")
    result = {"checked_at": now(), "live_unchanged": not differences,
              "differences": differences, "fingerprint_after": after}
    write_json(output / "live-integrity-after.json", result)
    return result


def state_codes(finding):
    values = finding.get("evidence_states", finding.get("states", []))
    if isinstance(values, dict):
        return [key for key, value in values.items() if value]
    return [value if isinstance(value, str) else value.get("code", value.get("state", ""))
            for value in values]


def finding_stats(finding):
    supports = finding.get("supports", [])
    pending = finding.get("missing", [])
    return {
        "status": finding.get("status"), "states": state_codes(finding),
        "supports": len(supports), "source_ids": sorted({s["source_id"] for s in supports}),
        "chunk_ids": sorted({s["chunk_id"] for s in supports}),
        "pending": len(pending),
        "pending_by_kind": dict(Counter(item.get("kind", "unknown") for item in pending)),
        "pending_by_code": dict(Counter(
            item.get("code", item.get("reason_code", "legacy")) for item in pending
        )),
        "candidate_documents": len(finding.get("candidate_documents", [])),
    }


def map_stats(mapping):
    findings = mapping.get("results", [])
    return {
        "run_id": mapping.get("id"), "status": mapping.get("status"),
        "requests": len(findings),
        "errors": sum(item.get("status") == "error" for item in findings),
        "analysis_error_requests": sum("analysis_error" in state_codes(item) for item in findings),
        "requests_with_support": sum(bool(item.get("supports")) for item in findings),
        "pending_total": sum(len(item.get("missing", [])) for item in findings),
        "pending_by_kind": dict(Counter(
            item.get("kind", "unknown")
            for finding in findings for item in finding.get("missing", [])
        )),
        "states": dict(Counter(code for finding in findings for code in state_codes(finding))),
        "retrieval_warning": mapping.get("retrieval_warning"),
    }


def report(output):
    manifest = read_json(output / "manifest.json")
    case = read_json(output / "baseline" / "case.json")
    before = read_json(output / "baseline" / "source-run.json")
    result_file = output / "results" / "sources.json"
    after = read_json(result_file) if result_file.exists() else None
    originals = {item["request_id"]: item for item in before["results"]}
    current = {item["request_id"]: item for item in (after or {}).get("results", [])}
    rows = []
    for request in case["identification"]["requests"]:
        old, new = originals.get(request["id"], {}), current.get(request["id"], {})
        row = {"request_id": request["id"], "label": request["label"],
               "title": request["title"], "description": request["description"],
               "before": finding_stats(old), "after": finding_stats(new) if new else None,
               "pending_before": old.get("missing", []), "pending_after": new.get("missing", []),
               "summary_before": old.get("summary"), "summary_after": new.get("summary"),
               "manual_review": "pending"}
        if new:
            row["support_sources_removed"] = sorted(
                set(row["before"]["source_ids"]) - set(row["after"]["source_ids"])
            )
            row["support_sources_added"] = sorted(
                set(row["after"]["source_ids"]) - set(row["before"]["source_ids"])
            )
        rows.append(row)
    comparison = {"created_at": now(), "case_id": manifest["case_id"],
                  "before": map_stats(before), "after": map_stats(after) if after else None,
                  "requests": rows, "manual_review": "pending", "institutional_approval": False}
    write_json(output / "comparison.json", comparison)
    lines = ["# Validación aislada de pendientes y comprobaciones", "",
             f"Expediente: `{manifest['case_id']}`; versión {manifest['case_version']}; "
             f"{manifest['request_count']} solicitudes confirmadas.", "",
             "Las llamadas y resultados pertenecen a una copia QA. No hay aprobaciones "
             "institucionales ni hechos confirmados por este harness.", "",
             f"Línea de base: {comparison['before']['pending_total']} pendientes, "
             f"{comparison['before']['requests_with_support']} solicitudes con respaldos "
             f"seleccionados y {comparison['before']['errors']} fallos de ejecución.", ""]
    if after:
        lines += [f"Resultado: {comparison['after']['pending_total']} pendientes, "
                  f"{comparison['after']['requests_with_support']} solicitudes con respaldos "
                  f"seleccionados y {comparison['after']['errors']} fallos de ejecución. "
                  f"{comparison['after']['analysis_error_requests']} solicitudes contienen "
                  "un error de análisis que debe revisarse.", ""]
    else:
        lines += ["La ejecución con IA está pendiente.", ""]
    lines += ["| Pregunta | Respaldos antes → después | Pendientes antes → después | Estados |",
              "|---|---:|---:|---|"]
    for row in rows:
        old, new = row["before"], row["after"] or {}
        states = ', '.join(new.get('states', [])) or 'Pendiente'
        lines.append(f"| {row['request_id']} · {row['label']} | {old['supports']} → "
                     f"{new.get('supports', '—')} | {old['pending']} → "
                     f"{new.get('pending', '—')} | {states} |")
    lines += ["", "La reducción del número de pendientes no prueba por sí sola una mejora. "
              "Se deben revisar alcance, citas, errores de lectura y tareas reales por pregunta. "
              "La comparación JSON conserva el texto completo de cada pendiente anterior y nuevo.",
              ""]
    (output / "COMPARACION.md").write_text("\n".join(lines), encoding="utf-8")
    draft_review_packet(output, case)
    return comparison


def draft_review_packet(output, case):
    """Presenta todas las respuestas y sus límites para la lectura manual posterior."""
    path = output / "results" / "drafts.json"
    if not path.is_file():
        return
    draft = read_json(path)
    results = {row["request_id"]: row for row in draft.get("results", [])}
    review_path = output / "results" / "reviews.json"
    review_rows = read_json(review_path).get("requests", []) if review_path.is_file() else []
    reviews = {row["request_id"]: row for row in review_rows}
    lines = ["# Respuestas QA para revisión manual", "",
             "Documento de trabajo de la copia aislada. Las respuestas no están aprobadas "
             "institucionalmente. La evaluación automática no sustituye la lectura manual.", ""]
    for request in case["identification"]["requests"]:
        row = results.get(request["id"], {})
        response = row.get("draft") or {}
        review = reviews.get(request["id"], {})
        lines += [f"## {request['id']} · {request['label']} · {request['title']}", "",
                  request["description"], "",
                  f"Estado del borrador: {row.get('status', 'pendiente')}. "
                  f"Evaluación de revisión: {review.get('status', 'pendiente')}.", ""]
        supports = {support["chunk_id"]: support for support in row.get("supports", [])}
        for paragraph in response.get("paragraphs", []):
            lines += [paragraph["text"], ""]
            for chunk_id in paragraph.get("cited_chunk_ids", []):
                support = supports.get(chunk_id, {})
                lines += [f"- Cita: {support.get('filename', chunk_id)}; "
                          f"página/sección {support.get('page', '—')}, "
                          f"líneas {support.get('line_start', '—')}"
                          f"–{support.get('line_end', '—')}."]
            if paragraph.get("cited_chunk_ids"):
                lines.append("")
        pending = response.get("pending", [])
        if pending:
            lines += ["Pendientes que conserva el borrador:", ""]
            lines += [f"- {item.get('stage', 'evidence')} · "
                      f"{item.get('reason_code', item['kind'])}: "
                      f"{item['description']}" for item in pending]
            lines.append("")
        issues = [*(row.get("checks") or {}).get("issues", []),
                  *(review.get("assessment") or {}).get("issues", [])]
        if issues:
            lines += ["Observaciones de las evaluaciones automáticas:", ""]
            lines += [f"- {item.get('description', item.get('message', str(item)))}"
                      for item in issues]
            lines.append("")
    (output / "RESPUESTAS_PARA_REVISAR.md").write_text("\n".join(lines), encoding="utf-8")


class CapturingSourceAssessor(OpenAISourceAssessor):
    """Conserva la selección estructurada para reproducir fallos sin repetir la IA."""

    def __init__(self, api_key, model, attempt):
        super().__init__(api_key, model)
        self.attempt = attempt
        self.active_request_id = None
        original_parse = self.client.responses.parse

        def parse_and_record(*args, **kwargs):
            response = original_parse(*args, **kwargs)
            write_json(self.attempt / "responses" / f"{self.active_request_id}.json",
                       response.model_dump(mode="json", warnings=False))
            return response

        self.client.responses.parse = parse_and_record

    def assess(self, request, candidates):
        self.active_request_id = request["id"]
        return super().assess(request, candidates)

    def _materialize(self, selection, request, candidates):
        write_json(self.attempt / "selections" / f"{request['id']}.json", {
            "request_id": request["id"], "selection": selection.model_dump(mode="json"),
        })
        return super()._materialize(selection, request, candidates)


class RecordingSourceAssessor:
    def __init__(self, delegate, attempt):
        self.delegate, self.attempt = delegate, attempt

    def assess(self, request, candidates):
        return record_call(self.attempt, "sources", request["id"], "assess",
                           {"request": request, "candidates": candidates},
                           lambda: self.delegate.assess(request, candidates))


class ReplaySourceAssessor:
    """Reaplica reglas; sólo refresca cambios con IA cuando se pide explícitamente."""

    def __init__(self, previous, attempt, fallback=None):
        self.previous, self.attempt = previous, attempt
        self.calls = 0
        self.fallback = fallback
        self.refreshed = []

    def changed(self, reason, request, candidates):
        self.refreshed.append({"request_id": request["id"], "reason": reason,
                               "real_ai": self.fallback is not None})
        write_json(self.attempt / "candidate-changes.json", self.refreshed)
        if self.fallback is None:
            raise ValueError(reason)
        return record_call(self.attempt, "sources", request["id"], "assess",
                           {"request": request, "candidates": candidates,
                            "refresh_reason": reason},
                           lambda: self.fallback.assess(request, candidates))

    def assess(self, request, candidates):
        captured = read_json(self.previous / "calls" / "sources" / f"{request['id']}-assess.json")
        selection = read_json(self.previous / "selections" / f"{request['id']}.json")["selection"]
        before = captured["inputs"]
        fields = ("id", "title", "description", "source_refs", "context", "case_id")
        if any(before["request"].get(key) != request.get(key) for key in fields):
            return self.changed("La petición o su contexto cambiaron.", request, candidates)
        # El orden y las puntuaciones pueden variar sin cambiar los documentos;
        # identidad, bytes, extracción, estado y contenido deben seguir iguales.
        ignored = {"score", "retrieval_score", "retrieval_channel", "adjacent_to"}
        original = {item["chunk_id"]: {key: value for key, value in item.items()
                                      if key not in ignored} for item in before["candidates"]}
        current = {item["chunk_id"]: {key: value for key, value in item.items()
                                     if key not in ignored} for item in candidates}
        if current != original:
            return self.changed("Cambiaron los candidatos de la búsqueda.", request, candidates)
        self.calls += 1
        write_json(self.attempt / "selections" / f"{request['id']}.json", {
            "request_id": request["id"], "selection": selection,
            "replayed_from": str(self.previous.relative_to(self.attempt.parent)),
        })
        return record_call(self.attempt, "sources", request["id"], "assess",
                           {"request": request, "candidates": candidates},
                           lambda: OpenAISourceAssessor._materialize(
                               _SourceSelection.model_validate(selection), request, candidates))


class RecordingDraftEngine:
    def __init__(self, delegate, attempt):
        self.delegate, self.attempt = delegate, attempt

    def plan(self, request, finding):
        return record_call(self.attempt, "drafts", request["id"], "plan",
                           {"request": request, "finding": finding},
                           lambda: self.delegate.plan(request, finding))

    def write(self, request, finding, plan):
        return record_call(self.attempt, "drafts", request["id"], "write", {"plan": plan},
                           lambda: self.delegate.write(request, finding, plan))

    def check(self, request, finding, plan, draft):
        return record_call(self.attempt, "drafts", request["id"], "check", {"draft": draft},
                           lambda: self.delegate.check(request, finding, plan, draft))


class RecordingReviewEngine:
    def __init__(self, delegate, attempt):
        self.delegate, self.attempt = delegate, attempt

    def assess(self, request, review):
        return record_call(self.attempt, "reviews", request["id"], "assess",
                           {"request": request, "review": review},
                           lambda: self.delegate.assess(request, review))


def record_call(attempt, phase, request_id, method, inputs, action):
    record = {"started_at": now(), "phase": phase, "request_id": request_id,
              "method": method, "inputs": inputs}
    path = attempt / "calls" / phase / f"{request_id}-{method}.json"
    write_json(path, record)
    started = time.monotonic()
    try:
        result = action()
        record["result"] = result
        return result
    except Exception as error:
        # Evita persistir mensajes de proveedores que pudieran incluir credenciales.
        record["error_type"] = type(error).__name__
        raise
    finally:
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(path, record)


def wait_service(output, attempt, phase, service, case_id, mapping, poll_seconds):
    previous = None
    while True:
        marker = (mapping.get("status"), mapping.get("completed_count"),
                  mapping.get("current_request_id"), mapping.get("current_step"))
        if marker != previous:
            log_event(output, "progress", phase=phase, status=marker[0], completed=marker[1],
                      total=mapping.get("total_count"), request_id=marker[2], step=marker[3])
            write_json(attempt / "results" / f"{phase}.json", mapping)
            previous = marker
        if mapping["status"] != "running":
            break
        time.sleep(poll_seconds)
        mapping = service.get(case_id)
    write_json(output / "results" / f"{phase}.json", mapping)
    return mapping


def run(output, settings, through, poll_seconds, retry_reviews, replay_from=None,
        refresh_changed=False):
    manifest = read_json(output / "manifest.json")
    data = qa_path(manifest["qa_data"])
    if data != output / "data":
        raise ValueError("El manifiesto no apunta a la base QA esperada.")
    if digest(read_json(output / "baseline" / "case.json")) != manifest["case_sha256"]:
        raise ValueError("Cambió la línea de base del expediente.")
    if not settings.api_key:
        raise ValueError("No hay clave OpenAI configurada; no se usará un simulador.")
    settings = replace(settings, data_dir=data)
    case_id = manifest["case_id"]
    attempt_id = now().replace(":", "").replace(".", "") + "_" + uuid4().hex[:8]
    attempt = output / "attempts" / attempt_id
    code = code_snapshot()
    versions = {}
    for name in ("openai", "langgraph", "langgraph-checkpoint-sqlite", "fastembed", "numpy"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = None
    execution = {"attempt_id": attempt_id, "started_at": now(), "status": "running",
                 "through": through, "model": settings.model, "semantic_model": MODEL_KEY,
                 "python": platform.python_version(), "dependencies": versions,
                 "git_head": head, "code_sha256": code, "code_snapshot_sha256": digest(code),
                 "data_dir": str(data), "case_id": case_id, "manual_review": "pending",
                 "institutional_approval": False, "phases": {}}
    replay = None
    if replay_from:
        previous = (output / "attempts" / replay_from).resolve(strict=True)
        if not previous.is_relative_to((output / "attempts").resolve()):
            raise ValueError("El intento de origen debe pertenecer a esta copia QA.")
        origin = read_json(previous / "execution.json")
        if origin.get("model") != settings.model:
            raise ValueError("El modelo configurado cambió respecto a la selección conservada.")
        fallback = CapturingSourceAssessor(settings.api_key, settings.model, attempt) \
            if refresh_changed else None
        replay = ReplaySourceAssessor(previous, attempt, fallback=fallback)
        execution.update(mode="selective_refresh" if fallback else "materialization_replay",
                         llm_calls=0, replayed_from=replay_from)
    else:
        execution["mode"] = "real_ai_workflow"
    write_json(attempt / "execution.json", execution)
    write_json(output / "execution.json", execution)
    library = SnapshotLibrary(data, manifest["originals_read_only_path"])
    cases = CaseStore(data)
    if digest(cases.get(case_id)) != manifest["case_sha256"]:
        raise ValueError("El expediente QA ya no corresponde a la copia exacta congelada.")
    source_engine = replay or RecordingSourceAssessor(
        CapturingSourceAssessor(settings.api_key, settings.model, attempt), attempt)
    verifications = SourceVerificationStore(data, library, cases)
    sources = SourceService(settings, cases, library, assessor=source_engine,
                            verifications=verifications)
    drafts = DraftService(settings, cases, library, sources,
                          engine=RecordingDraftEngine(
                              OpenAIDraftEngine(settings.api_key, settings.model), attempt))
    reviews = ReviewService(settings, cases, library, sources, drafts,
                            engine=RecordingReviewEngine(
                                OpenAIReviewEngine(settings.api_key, settings.model), attempt))
    try:
        sources.library.recover()
        drafts.store.recover()
        reviews.recover()
        log_event(output, "starting", attempt_id=attempt_id, through=through, data_dir=str(data))
        mapping = wait_service(output, attempt, "sources", sources, case_id,
                               sources.start(case_id, manifest["case_version"]), poll_seconds)
        execution["phases"]["sources"] = {"status": mapping["status"], "id": mapping.get("id")}
        if mapping["status"] != "ready" or mapping.get("stale"):
            raise ValueError("La búsqueda QA no terminó correctamente; se conserva el avance.")
        if through in {"drafts", "reviews"}:
            if code_snapshot() != code:
                raise ValueError("El código cambió durante la búsqueda. Reanude con otro intento.")
            draft_run = wait_service(output, attempt, "drafts", drafts, case_id,
                                     drafts.start(case_id, manifest["case_version"]), poll_seconds)
            execution["phases"]["drafts"] = {
                "status": draft_run["status"], "id": draft_run.get("id")}
            if draft_run["status"] not in {"ready", "partial"} or any(
                item["status"] == "error" for item in draft_run.get("results", [])
            ):
                raise ValueError("Los borradores QA no terminaron; se conserva el avance.")
        if through == "reviews":
            if code_snapshot() != code:
                raise ValueError("El código cambió durante los borradores. Reanude el intento.")
            review_run = reviews.start(case_id, manifest["case_version"])
            for request in review_run["requests"]:
                if request.get("approval"):
                    raise ValueError("La copia QA contiene una aprobación inesperada.")
                if not retry_reviews and request.get("assessment") and request["status"] != "error":
                    continue
                request = reviews.assess(case_id, request["request_id"], request["revision"])
                log_event(output, "progress", phase="reviews", request_id=request["request_id"],
                          status=request["status"])
                while request["status"] == "checking":
                    time.sleep(poll_seconds)
                    request = reviews.store.get(case_id, request["request_id"])
                log_event(output, "progress", phase="reviews", request_id=request["request_id"],
                          status=request["status"],
                          assessment=(request.get("assessment") or {}).get("status"))
                review_run = reviews.get(case_id)
                write_json(attempt / "results" / "reviews.json", review_run)
                write_json(output / "results" / "reviews.json", review_run)
            review_run = reviews.get(case_id)
            execution["phases"]["reviews"] = {
                "status": review_run["status"], "requests": len(review_run["requests"]),
                "errors": sum(row["status"] == "error" for row in review_run["requests"]),
                "approved_count": review_run["approved_count"],
            }
            if execution["phases"]["reviews"]["errors"]:
                raise ValueError("Hay errores de evaluación QA; se conservan los resultados.")
        execution["status"] = "completed"
    except Exception as error:
        execution.update(status="error", error_type=type(error).__name__)
        raise
    finally:
        reviews.close()
        drafts.close()
        sources.close()
        execution["finished_at"] = now()
        execution["code_unchanged_during_run"] = code_snapshot() == code
        execution["live_integrity"] = verify_integrity(output)
        execution["case_copy_unchanged"] = digest(cases.get(case_id)) == manifest["case_sha256"]
        if replay:
            execution["materialized_selections"] = replay.calls
            execution["refreshed_requests"] = replay.refreshed
            execution["llm_calls"] = len(list((attempt / "responses").glob("*.json")))
        write_json(attempt / "execution.json", execution)
        write_json(output / "execution.json", execution)
        report(output)
        log_event(output, "finished", attempt_id=attempt_id, status=execution["status"],
                  phases=execution["phases"],
                  live_unchanged=execution["live_integrity"]["live_unchanged"])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",
                        choices=("prepare", "run", "rematerialize", "report", "integrity"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-data", type=Path, default=ROOT / "data")
    parser.add_argument("--case-id", default=DEFAULT_CASE)
    parser.add_argument("--baseline", type=Path, default=(
        ROOT / "output" / "qa" / "context-retrieval-20260908" / "live-after.json"
    ))
    parser.add_argument("--through", choices=("sources", "drafts", "reviews"), default="reviews")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--retry-reviews", action="store_true")
    parser.add_argument("--from-attempt", help="Intento de IA cuyas selecciones se reutilizan.")
    parser.add_argument("--refresh-changed", action="store_true",
                        help="En rematerialize, usa IA sólo si cambiaron candidatos o contexto.")
    args = parser.parse_args()
    output = qa_path(args.output_dir)
    if not 0.2 <= args.poll_seconds <= 30:
        parser.error("poll-seconds debe estar entre 0.2 y 30 segundos.")
    if args.command == "prepare":
        prepare(output, args.source_data, args.case_id, args.baseline)
    elif args.command == "run":
        run(output, Settings.load(), args.through, args.poll_seconds, args.retry_reviews)
    elif args.command == "rematerialize":
        if not args.from_attempt:
            parser.error("rematerialize requiere --from-attempt.")
        run(output, Settings.load(), "sources", args.poll_seconds, False,
            replay_from=args.from_attempt, refresh_changed=args.refresh_changed)
    elif args.command == "report":
        result = report(output)
        print(json.dumps({key: result[key] for key in ("before", "after")}, ensure_ascii=False))
    else:
        result = verify_integrity(output)
        print(json.dumps({key: result[key] for key in ("live_unchanged", "differences")},
                         ensure_ascii=False))
        if not result["live_unchanged"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
