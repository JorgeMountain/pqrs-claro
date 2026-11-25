"""Read-only full-library loader and isolated baseline retrieval profile.

No SourceLibrary is instantiated and no live database is opened writable. The
semantic cache/model and lexical payloads are copied to the QA directory. This
module can be imported by an A/B harness to share one in-memory corpus.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import importlib
import importlib.util
import io
import json
import os
import pstats
import shutil
import sqlite3
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "output/qa/full-library-retrieval-20261117"
BASELINE = COMMON / "baseline-master/src/pqrs_claro"
CASE_ID = "a7293f8bd21d490faf7be8d69d3c2f81"
RUN_ID = "bfca5c38385c470182989c6f5e6608dd"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ro(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def baseline_package(path=BASELINE):
    """Load the frozen package under a separate name; never import live selector."""
    name = "_rag_full_library_master"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(path) / "__init__.py", submodule_search_locations=[str(path)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


def baseline_module(name, path=BASELINE):
    return importlib.import_module(baseline_package(path) + "." + name)


def load_case_requests(data_dir=ROOT / "data", case_id=CASE_ID):
    """Return request_id -> exact request recorded at its latest checkpoint."""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer()
    requests = {}
    with closing(_ro(Path(data_dir) / "source_checkpoints.sqlite")) as connection:
        rows = connection.execute(
            "SELECT thread_id,max(checkpoint_id) FROM checkpoints WHERE thread_id LIKE ? "
            "GROUP BY thread_id",
            (case_id + ":%",),
        ).fetchall()
        for thread_id, checkpoint_id in rows:
            kind, blob = connection.execute(
                "SELECT type,checkpoint FROM checkpoints WHERE thread_id=? AND checkpoint_id=?",
                (thread_id, checkpoint_id),
            ).fetchone()
            values = serde.loads_typed((kind, blob))["channel_values"]
            request = values.get("request")
            if request and request.get("id"):
                requests[request["id"]] = request
    return requests


def load_full_library(
    output,
    *,
    data_dir=ROOT / "data",
    case_id=CASE_ID,
    run_id=RUN_ID,
    verify_originals=True,
    baseline_path=BASELINE,
):
    """Return (chunks, prepared_terms, scope, manifest, case_requests).

    Scope is {case_id, allowed_collection_ids}. The original run fixes the
    document order and versions. Current ACLs and eligibility must still match.
    A seal is saved on the first load and compared on later loads; a changed
    corpus fails instead of silently changing the A/B experiment.
    """
    output, data_dir = Path(output), Path(data_dir)
    output.mkdir(parents=True, exist_ok=True)
    library = baseline_module("source_library", baseline_path)
    preparation = baseline_module("source_preparation", baseline_path)
    retrieval = baseline_module("source_retrieval", baseline_path)
    times, seals, chunks = {}, [], []
    started = time.perf_counter()
    lexical_path = output / "lexical.sqlite"
    lexical_new = not lexical_path.exists()
    with closing(_ro(data_dir / "biblioteca.sqlite")) as connection:
        connection.execute("BEGIN")
        run = json.loads(
            connection.execute(
                "SELECT body FROM source_runs WHERE id=? AND case_id=?", (run_id, case_id)
            ).fetchone()[0]
        )
        scope = {"case_id": case_id, "allowed_collection_ids": run["allowed_collection_ids"]}
        current_allowed = [
            row[0]
            for row in connection.execute(
                "SELECT collection_id FROM case_source_collections WHERE case_id=? "
                "ORDER BY collection_id",
                (case_id,),
            )
        ]
        if sorted(current_allowed) != sorted(scope["allowed_collection_ids"]):
            raise RuntimeError("Collection permissions differ from the recorded source run")
        rows = connection.execute(
            "SELECT s.id FROM sources s INDEXED BY sources_collection_scope WHERE "
            "COALESCE(json_extract(s.body,'$.collection_id'),'') IN "
            "(SELECT '' UNION SELECT collection_id FROM case_source_collections WHERE case_id=?) "
            "AND (json_extract(s.body,'$.case_id') IS NULL OR json_extract(s.body,'$.case_id')=?) "
            "AND s.version=(SELECT max(other.version) FROM sources other "
            "WHERE other.document_id=s.document_id) "
            "AND COALESCE(json_extract(s.body,'$.validity'),'')!='superseded' "
            "AND COALESCE(json_extract(s.body,'$.category'),'') "
            "NOT IN ('previous_response','archive_only') "
            "AND (json_type(s.body,'$.extraction_status') IS NULL OR "
            "json_extract(s.body,'$.extraction_status') IN ('ready','partial')) "
            "ORDER BY s.rowid DESC",
            (case_id, case_id),
        ).fetchall()
        ids = [source["id"] for source in run["source_snapshot"]]
        if ids != [row[0] for row in rows]:
            raise RuntimeError("Current eligible documents/order differ from the saved run")
        snapshot = {source["id"]: source for source in run["source_snapshot"]}
        bytes_checked = 0
        for offset in range(0, len(ids), 200):
            batch = ids[offset : offset + 200]
            rows = {
                row[0]: row[1:]
                for row in connection.execute(
                    "SELECT id,body,pages FROM sources WHERE id IN ("
                    + ",".join("?" for _ in batch)
                    + ")",
                    batch,
                )
            }
            for source_id in batch:
                body, pages_json = rows[source_id]
                source = {**json.loads(body), "is_latest": True}
                recorded = snapshot[source_id]
                if source != recorded:
                    raise RuntimeError("Source metadata changed since source run: " + source_id)
                if not retrieval.source_in_scope(scope, source):
                    raise RuntimeError("Source outside recorded permissions: " + source_id)
                original = (
                    data_dir
                    / "library"
                    / source_id
                    / ("original" + Path(source["filename"]).suffix.lower())
                )
                if verify_originals:
                    with original.open("rb") as handle:
                        actual = hashlib.file_digest(handle, "sha256").hexdigest()
                    if actual != source["sha256"]:
                        raise RuntimeError("Original file integrity mismatch: " + source_id)
                    bytes_checked += original.stat().st_size
                source_chunks = library.make_chunks(source, json.loads(pages_json))
                chunks.extend(source_chunks)
                seals.append(
                    {
                        "id": source_id,
                        "version": source["version"],
                        "sha256": source["sha256"],
                        "metadata_sha256": _hash(_json(source)),
                        "pages_sha256": _hash(pages_json),
                        "chunks_sha256": _hash(_json(source_chunks)),
                        "chunk_count": len(source_chunks),
                    }
                )
            if offset % 2000 == 0:
                print(f"load {min(offset + 200, len(ids))}/{len(ids)} sources", flush=True)
        times["corpus_read_integrity_chunks_seconds"] = time.perf_counter() - started
        started = time.perf_counter()
        if lexical_new:
            temporary_lexical = output / "lexical-copying.sqlite"
            if temporary_lexical.exists():
                temporary_lexical.unlink()
            with closing(sqlite3.connect(temporary_lexical)) as copied, copied:
                copied.execute(
                    "CREATE TABLE source_index_jobs (source_id TEXT PRIMARY KEY, "
                    "status TEXT, algorithm TEXT, payload TEXT, payload_hash TEXT)"
                )
                for offset in range(0, len(ids), 200):
                    batch = ids[offset : offset + 200]
                    rows = connection.execute(
                        "SELECT source_id,status,algorithm,payload,payload_hash "
                        "FROM source_index_jobs "
                        "WHERE source_id IN (" + ",".join("?" for _ in batch) + ")",
                        batch,
                    )
                    copied.executemany("INSERT INTO source_index_jobs VALUES (?,?,?,?,?)", rows)
            temporary_lexical.replace(lexical_path)
        times["lexical_snapshot_seconds"] = time.perf_counter() - started
    manifest = {
        "schema": 1,
        "case_id": case_id,
        "run_id": run_id,
        "source_count": len(seals),
        "chunk_count": len(chunks),
        "allowed_collection_ids": scope["allowed_collection_ids"],
        "corpus_sha256": _hash(_json(seals)),
        "sources": seals,
        "originals_checked": verify_originals,
        "original_bytes_checked": bytes_checked,
    }
    seal_path = output / "corpus-seal.json"
    if seal_path.exists():
        previous = json.loads(seal_path.read_text(encoding="utf-8"))
        if previous["corpus_sha256"] != manifest["corpus_sha256"]:
            raise RuntimeError("Corpus changed after first QA load; use a new experiment")
    else:
        seal_path.write_text(_json(manifest), encoding="utf-8")

    class ReadOnlyLexicalSnapshot:
        @contextmanager
        def connect(self):
            with closing(_ro(lexical_path)) as connection:
                yield connection

    started = time.perf_counter()
    prepared_terms = preparation.load_terms(ReadOnlyLexicalSnapshot(), chunks)
    times["load_prepared_terms_seconds"] = time.perf_counter() - started
    manifest["prepared_terms_count"] = len(prepared_terms)
    manifest["timings"] = times
    requests = load_case_requests(data_dir, case_id)
    request_path = output / "case-requests.json"
    request_seal = _hash(_json(requests))
    if (
        request_path.exists()
        and _hash(_json(json.loads(request_path.read_text(encoding="utf-8")))) != request_seal
    ):
        raise RuntimeError("Recorded requests changed after first QA load")
    request_path.write_text(_json(requests), encoding="utf-8")
    manifest["requests_sha256"] = request_seal
    return chunks, prepared_terms, scope, manifest, requests


def copy_semantic_cache(output, *, data_dir=ROOT / "data"):
    """SQLite backup from read-only source plus independent local model files."""
    target = Path(output) / "semantic"
    target.mkdir(parents=True, exist_ok=True)
    source = Path(data_dir) / "semantic"
    database = target / "embeddings.sqlite"
    if not database.exists():
        temporary = target / "embeddings-copying.sqlite"
        with closing(_ro(source / "embeddings.sqlite")) as original:
            with closing(sqlite3.connect(temporary)) as copied:
                original.backup(copied, pages=8192)
        temporary.replace(database)
    model = baseline_module("source_semantic")
    for filename in (
        model.MODEL_FILE,
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "onnx/special_tokens_map.json",
    ):
        original = source / "models" / model.MODEL_REVISION / filename
        copied = target / "models" / model.MODEL_REVISION / filename
        if not copied.exists():
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, copied)
    return target


def prepare_runtime(
    chunks,
    prepared_terms,
    output,
    *,
    retrieval_module=None,
    semantic=None,
    semantic_module=None,
    data_dir=ROOT / "data",
    warm_model=True,
):
    """Return (lexical_index, semantic_index, timings); reuse semantic in A/B."""
    retrieval = retrieval_module or baseline_module("source_retrieval")
    lexical = retrieval.RetrievalIndex(chunks, prepared_terms=prepared_terms)
    times = {}
    if semantic is None:
        started = time.perf_counter()
        cache = copy_semantic_cache(output, data_dir=data_dir)
        times["semantic_isolation_seconds"] = time.perf_counter() - started
        model = semantic_module or baseline_module("source_semantic")
        semantic = model.SemanticIndex(cache, preparation_budget_seconds=0)
        started = time.perf_counter()
        complete = semantic.prepare(chunks)
        times["semantic_prepare_seconds"] = time.perf_counter() - started
        if not complete or not semantic.diagnostics["complete"] or semantic.diagnostics["encoded"]:
            raise RuntimeError("Full cached E5 coverage required: " + _json(semantic.diagnostics))
        if warm_model:
            started = time.perf_counter()
            semantic._embedding_model()
            times["resident_model_load_seconds"] = time.perf_counter() - started
    return lexical, semantic, times


def candidate_summary(row):
    return {
        key: row.get(key)
        for key in (
            "source_id",
            "chunk_id",
            "page",
            "line_start",
            "line_end",
            "method",
            "needs_review",
            "retrieval_channel",
            "retrieval_score",
            "semantic_score",
        )
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=COMMON / "profile")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    chunks, terms, scope, manifest, requests = load_full_library(args.output)
    print("corpus ready", manifest["source_count"], manifest["chunk_count"], flush=True)
    index, semantic, times = prepare_runtime(chunks, terms, args.output)
    print("runtime ready", times, flush=True)
    retrieval = baseline_module("source_retrieval")
    results = {}
    for request_id in ("P2", "P4"):
        profiler = cProfile.Profile() if request_id == "P2" else None
        started = time.perf_counter()
        if profiler:
            profiler.enable()
        selected = retrieval.retrieve(requests[request_id], chunks, index=index, semantic=semantic)
        if profiler:
            profiler.disable()
        elapsed = time.perf_counter() - started
        results[request_id] = {
            "seconds": elapsed,
            "profiled": bool(profiler),
            "candidates": [candidate_summary(row) for row in selected],
            "lexical": dict(index.diagnostics),
            "semantic": dict(semantic.diagnostics),
        }
        if profiler:
            profiler.dump_stats(args.output / "P2-baseline.pstats")
            stream = io.StringIO()
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(
                65
            )
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("tottime").print_stats(40)
            (args.output / "P2-baseline-profile.txt").write_text(
                stream.getvalue(), encoding="utf-8"
            )
        print(request_id, round(elapsed, 3), "seconds; profiled=", bool(profiler), flush=True)
    report = {
        "manifest": {key: value for key, value in manifest.items() if key != "sources"},
        "runtime_timings": times,
        "scope": scope,
        "queries": results,
        "note": "P2 includes profiler overhead and first index/matrix build; "
        "P4 is warm runtime without profiler. These are not comparable A/B timings.",
    }
    (args.output / "profile-results.json").write_text(_json(report), encoding="utf-8")


if __name__ == "__main__":
    main()
