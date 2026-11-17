"""Compare frozen code on new fictional PDFs; keep the rubric outside model payloads.

Without --run-api this only prepares isolated PDFs/databases and seals the rubric.
Run each variant once, in its own process, with an explicit frozen --code-root.
Identification is seeded and literally checked, not evaluated as an AI stage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import sys
import textwrap
import threading
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "tests/fixtures"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def emit(**value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_hashes(code):
    return {str(p.relative_to(code)): sha(p)
            for p in sorted((code / "src/pqrs_claro").rglob("*.py"))}


def pdf_bytes(pages):
    import pymupdf

    with pymupdf.open() as doc:
        for paragraphs in pages:
            lines = [line for p in paragraphs for line in textwrap.wrap(p, width=125)]
            assert len(lines) < 65
            page = doc.new_page(width=1000, height=1100)
            page.insert_text((35, 40), "\n".join(lines), fontsize=10, lineheight=1.5)
        return doc.tobytes(garbage=4, deflate=True)


def prepare(output, content, fixture_prefix="request_trace_generalization"):
    from pqrs_claro.extraction import PDFExtractor
    from pqrs_claro.models import Identification, validate_identification
    from pqrs_claro.source_library import SourceLibrary
    from pqrs_claro.storage import CaseStore, now

    filenames = (f"{fixture_prefix}_content.json", f"{fixture_prefix}_rubric.json")
    seal = {name: sha(FIXTURES / name) for name in filenames}
    manifest_path = output / "seed-manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert existing["fixture_hashes"] == seal, "Sealed fixtures changed"
        return existing
    assert not (output / "seed-data").exists(), "Inspect incomplete seed; never overwrite it"
    for name in filenames:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURES / name, target)
    save(output / "sealed-before-api.json", {
        "at": now(), "fixture_hashes": seal, "api_calls": 0,
        "rubric_sent_to_model": False,
    })
    cases = CaseStore(output / "seed-data")
    library = SourceLibrary(output / "seed-data", PDFExtractor())
    library.save_collection({"id": "trace-shared", "title": "Corpus ficticio de seguimiento",
                             "name": "QA seguimiento"})
    source_rows = []
    for source in content["sources"]:
        blob = pdf_bytes(source["pages"])
        (output / f"{source['key']}.pdf").write_bytes(blob)
        row = library.add(f"{source['key']}.pdf", blob, title=source["title"],
                          category=source["category"], collection_id="trace-shared",
                          origin="Corpus enteramente ficticio, sin autoridad institucional real.")
        if source["review"]:
            row = library.review(row["id"], reviewed_by="QA ficción",
                                 review_note="Revisión del fixture ficticio, sin valor real.",
                                 validity=source["validity"])
        source_rows.append({"key": source["key"], "source": row})
    case_rows = []
    for fixture in content["cases"]:
        blob = pdf_bytes([[*fixture["introduction"], *fixture["questions"]]])
        (output / f"{fixture['id']}.pdf").write_bytes(blob)
        row = cases.create(f"{fixture['id']}.pdf", blob, case_id=fixture["id"])
        pages = PDFExtractor().extract(cases.original(row["id"]))
        lines = pages[0].text.splitlines()
        requests = []
        for index, question in enumerate(fixture["questions"], 1):
            quote_lines = textwrap.wrap(question, width=125)
            start = lines.index(quote_lines[0])
            assert lines[start:start + len(quote_lines)] == quote_lines
            requests.append({"id": f"P{index}", "label": str(index), "title": f"Petición {index}",
                             "description": question, "parent_id": None, "source_refs": [{
                                 "page": 1, "line_start": start + 1,
                                 "line_end": start + len(quote_lines),
                                 "quote": "\n".join(quote_lines)}]})
        identified = Identification(subject=fixture["title"], requester=None,
                                    document_date="2026-11-17", requests=requests, warnings=[])
        validate_identification(identified, pages)
        row = cases.update(row["id"], expected=row["version"], status="confirmed",
                           pages=[p.model_dump() for p in pages],
                           identification=identified.model_dump(), request_count=len(requests),
                           confirmed_at=now(), mode="real",
                           event="QA identificación literal fijada")
        library.link_collections(row["id"], ["trace-shared"])
        case_rows.append({"case_id": row["id"], "sha256": row["sha256"]})
    manifest = {"fixture_hashes": seal, "cases": case_rows, "sources": source_rows,
                "identification_seeded": True, "ocr_tested": False,
                "chunks": len(library.snapshot(case_rows[0]["case_id"])[1])}
    save(manifest_path, manifest)
    return manifest


def settings_for(data):
    from pqrs_claro.config import Settings

    # Read the existing project key without printing or persisting credentials.
    spec = importlib.util.spec_from_file_location("_trace_qa_config",
                                                  PROJECT / "src/pqrs_claro/config.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    actual = module.Settings.load()
    assert actual.api_key, "Existing project API key unavailable"
    return replace(Settings(), data_dir=data, api_key=actual.api_key, model=actual.model,
                   source_concurrency=5, draft_concurrency=3, source_service_tier="fast",
                   procedure_scope_pilot=False)


def wait_for(service, cid, seconds=700):
    started = last = time.perf_counter()
    while cid in service.active:
        time.sleep(.1)
        if time.perf_counter() - last > 15:
            emit(event="working", case_id=cid, seconds=round(time.perf_counter() - started, 1))
            last = time.perf_counter()
        if time.perf_counter() - started > seconds:
            raise TimeoutError("Bounded QA wait exceeded")


def citations(library, cid, run):
    result = []
    for row in run.get("results", []):
        for support in row.get("supports", []):
            document = library.get(support["source_id"], cid)
            page = next(p for p in document["pages"] if p["number"] == support["page"])
            literal = "\n".join(page["text"].splitlines()[
                support["line_start"] - 1:support["line_end"]])
            result.append({"request_id": row["request_id"], "chunk_id": support["chunk_id"],
                           "literal": literal == support["quote"],
                           "version": document["source"]["version"] == support["version"],
                           "hash": sha(library.original(support["source_id"], cid))
                           == support["sha256"], "permission": document["source"]["collection_id"]
                           in library.linked_collections(cid)})
    return result


def observe_api(target, max_calls):
    from openai.resources.responses.responses import Responses

    from pqrs_claro.performance_metrics import _scope

    original = Responses.parse
    lock = threading.Lock()
    counter = 0

    def observed(resource, *args, **kwargs):
        nonlocal counter
        with lock:
            counter += 1
            sequence = counter
        if sequence > max_calls:
            raise RuntimeError("QA API call limit reached; preserve the partial result")
        allowed = ("model", "input", "instructions", "store", "truncation",
                   "max_output_tokens", "reasoning", "service_tier")
        request = {key: deepcopy(kwargs[key]) for key in allowed if key in kwargs}
        schema = kwargs.get("text_format")
        if schema:
            request["text_format_name"] = schema.__name__
            request["text_format_schema"] = schema.model_json_schema()
        scope = _scope.get() or {}
        metadata = {key: scope.get(key) for key in ("case_id", "request_id", "stage", "run_id")}
        save(target / "api" / f"{sequence:03d}-request.json",
             {"scope": metadata, "request": request})
        started = time.perf_counter()
        try:
            result = original(resource, *args, **kwargs)
        except Exception as exc:
            save(target / "api" / f"{sequence:03d}-response.json", {
                "ok": False, "error_type": type(exc).__name__, "error": str(exc),
                "seconds": time.perf_counter() - started})
            raise
        save(target / "api" / f"{sequence:03d}-response.json", {
            "ok": True, "response": result.model_dump(mode="json", warnings=False),
            "seconds": time.perf_counter() - started})
        return result

    Responses.parse = observed
    return lambda: setattr(Responses, "parse", original)


def run(args, content, manifest):
    from pqrs_claro.draft_service import DraftService
    from pqrs_claro.extraction import PDFExtractor
    from pqrs_claro.performance_metrics import read_metrics
    from pqrs_claro.source_library import SourceLibrary
    from pqrs_claro.source_semantic import MODEL_REVISION, SemanticIndex
    from pqrs_claro.source_service import SourceService
    from pqrs_claro.storage import CaseStore

    target = args.output / "runs" / args.variant
    assert not target.exists(), "Keep prior runs immutable; select a new variant name"
    data = target / "data"
    source_run = args.draft_from_run
    shutil.copytree(source_run / "data" if source_run else args.output / "seed-data", data)
    if not (data / "semantic/models" / MODEL_REVISION).exists():
        shutil.copytree(PROJECT / "data/semantic/models" / MODEL_REVISION,
                        data / "semantic/models" / MODEL_REVISION)
    settings = settings_for(data)
    cases, library = CaseStore(data), SourceLibrary(data, PDFExtractor())
    sources = SourceService(settings, cases, library)
    drafts = DraftService(settings, cases, library, sources)
    hashes = code_hashes(args.code_root)
    state = {"code_root": str(args.code_root), "code_hashes": hashes,
             "fixture_hashes": manifest["fixture_hashes"], "model": settings.model,
             "source_service_tier": settings.source_service_tier,
             "procedure_scope_pilot": False, "rubric_sent_to_model": False,
             "identification_seeded": True, "api_limit": args.max_calls,
             "source_only": args.source_only, "cases": {}}
    if source_run:
        previous = json.loads((source_run / "state.json").read_text(encoding="utf-8"))
        assert previous["fixture_hashes"] == manifest["fixture_hashes"]
        assert previous["model"] == settings.model
        state["reused_source_run"] = {
            "path": str(source_run), "state_sha256": sha(source_run / "state.json"),
            "sources_sha256": {p.parent.name: sha(p)
                               for p in sorted(source_run.glob("*/sources.json"))},
        }
    restore = observe_api(target, args.max_calls)
    source_module = importlib.import_module("pqrs_claro.source_service")
    original_retrieve = source_module.retrieve
    capture = {}
    lock = threading.Lock()

    def retrieve(request, chunks, **kwargs):
        result = original_retrieve(request, chunks, **kwargs)
        with lock:
            capture.setdefault("retrievals", []).append({"request": deepcopy(request),
                                                        "candidates": deepcopy(result)})
        return result

    source_module.retrieve = retrieve
    originals = (library.save_run_progress, library.save_run)

    def saving(value, method):
        result = method(value)
        if capture.get("case_id") == value.get("case_id"):
            for row in value.get("results", []):
                if row.get("supports"):
                    capture.setdefault("citation_seconds", {}).setdefault(
                        row["request_id"], time.perf_counter() - capture["start"])
        return result

    library.save_run_progress = lambda value: saving(value, originals[0])
    library.save_run = lambda value: saving(value, originals[1])
    try:
        started = time.perf_counter()
        if not source_run:
            sources.semantic_model(data / "semantic")
            chunks = library.snapshot(manifest["cases"][0]["case_id"])[1]
            SemanticIndex(data / "semantic", model_factory=sources.semantic_model).prepare(chunks)
        state["prepare_seconds"] = time.perf_counter() - started
        save(target / "state.json", state)
        for fixture in content["cases"]:
            cid = fixture["id"]
            if args.only and cid not in args.only.split(","):
                continue
            case = cases.get(cid)
            capture.clear()
            capture.update(case_id=cid, start=time.perf_counter(), retrievals=[])
            row = state["cases"].setdefault(cid, {})
            try:
                if not source_run:
                    sources.start(cid, case["version"])
                    wait_for(sources, cid)
                found = sources.get(cid, compact=True)
                if source_run:
                    assert not found.get("stale"), "Frozen source run is incompatible with code"
                    assert found["status"] == "ready", "Reuse only completed source analysis"
                    original = json.loads((source_run / cid / "sources.json").read_text(
                        encoding="utf-8"))
                    assert found["id"] == original["id"]
                    assert found["results"] == original["results"], "Source result changed on reuse"
                    row["reused_source_run_id"] = found["id"]
                row.update(source_seconds=time.perf_counter() - capture["start"],
                           citation_seconds=capture.get("citation_seconds", {}),
                           source_status=found["status"])
                save(target / cid / "sources.json", found)
                save(target / cid / "retrievals.json", capture["retrievals"])
                save(target / cid / "citations.json", citations(library, cid, found))
                if args.source_only:
                    row["total_seconds"] = time.perf_counter() - capture["start"]
                    emit(event="source_complete", variant=args.variant, case_id=cid,
                         seconds=round(row["total_seconds"], 2), status=found["status"])
                    continue
                drafts.start(cid, case["version"])
                wait_for(drafts, cid)
                drafted = drafts.get(cid)
                row.update(total_seconds=time.perf_counter() - capture["start"],
                           draft_status=drafted["status"])
                save(target / cid / "drafts.json", drafted)
                emit(event="case_complete", variant=args.variant, case_id=cid,
                     seconds=round(row["total_seconds"], 2), status=drafted["status"])
            except Exception as exc:
                row["error"] = {"type": type(exc).__name__, "message": str(exc)}
                emit(event="case_error", case_id=cid, error_type=type(exc).__name__)
            finally:
                save(target / cid / "metrics.json", read_metrics(data, cid))
                save(target / "state.json", state)
    finally:
        sources.close()
        drafts.close()
        restore()
        source_module.retrieve = original_retrieve
        library.save_run_progress, library.save_run = originals
        state["code_unchanged"] = hashes == code_hashes(args.code_root)
        state["loaded_modules"] = {
            name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
            if name.startswith("pqrs_claro") and getattr(module, "__file__", None)}
        state["isolated_imports"] = all(Path(path).is_relative_to(args.code_root / "src")
                                        for path in state["loaded_modules"].values())
        save(target / "state.json", state)
        assert state["code_unchanged"] and state["isolated_imports"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-root", type=Path, default=PROJECT)
    parser.add_argument("--output", type=Path,
                        default=PROJECT / "output/qa/trace-generalization-20261117")
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--run-api", action="store_true")
    parser.add_argument("--fixture-prefix", default="request_trace_generalization")
    parser.add_argument("--source-only", action="store_true",
                        help="Evaluate retrieval/reader only; do not call drafting models")
    parser.add_argument("--draft-from-run", type=Path,
                        help="Clone a completed source-only run and draft without calling reader")
    parser.add_argument("--only", help="Comma-separated case IDs; default all six questions")
    parser.add_argument("--max-calls", type=int, default=36)
    args = parser.parse_args()
    args.output, args.code_root = args.output.resolve(), args.code_root.resolve()
    if args.draft_from_run:
        args.draft_from_run = args.draft_from_run.resolve()
        assert not args.source_only, "Select source-only or draft-from-run, not both"
        assert args.draft_from_run.is_relative_to(PROJECT / "output/qa")
        assert (args.draft_from_run / "state.json").is_file()
        assert (args.draft_from_run / "data").is_dir()
    assert args.output.is_relative_to(PROJECT / "output/qa")
    assert (args.code_root / "src/pqrs_claro/config.py").is_file()
    assert args.variant.replace("-", "").replace("_", "").isalnum()
    assert args.fixture_prefix.replace("_", "").isalnum()
    assert args.max_calls > 0
    sys.path.insert(0, str(args.code_root / "src"))
    sys.stdout.reconfigure(encoding="utf-8")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    content = json.loads((FIXTURES / f"{args.fixture_prefix}_content.json").read_text(
        encoding="utf-8"))
    manifest = prepare(args.output, content, args.fixture_prefix)
    emit(event="prepared", cases=len(manifest["cases"]), sources=len(manifest["sources"]),
         chunks=manifest["chunks"], api_calls=0)
    if args.run_api:
        run(args, content, manifest)


if __name__ == "__main__":
    main()
