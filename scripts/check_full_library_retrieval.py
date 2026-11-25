"""Compare the full authorized library; rubric never enters retrieval or API input.

First run retrieval only. --run-api reuses sealed candidate files and performs
one bounded reading per variant/question with the same production reader.
No live case, source, checkpoint or verification record is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path

from profile_full_library_retrieval import (
    COMMON,
    ROOT,
    baseline_module,
    load_full_library,
    prepare_runtime,
)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(text):
    return " ".join(unicodedata.normalize("NFKC", str(text)).split())


def obligations(rule, candidates):
    return {
        group["id"]: any(
            source.get("source_id") == alternative["source_id"]
            and source.get("page") == alternative["page"]
            and plain(alternative["quote"]) in plain(source.get("quote", ""))
            for alternative in group["alternatives"]
            for source in candidates
        )
        for group in rule.get("required_alternatives", [])
    }


def fixture_requests(content, scope, saved):
    from pqrs_claro.request_intent import classify_request_intent
    from pqrs_claro.source_context import build_source_requests

    results = {}
    for fixture in content["cases"]:
        lines = list(fixture["introduction"])
        requests = []
        for number, question in enumerate(fixture["questions"], 1):
            lines.append(question["text"])
            requests.append(
                {
                    "id": question["id"],
                    "label": str(number),
                    "title": question["text"],
                    "description": question["text"],
                    "parent_id": None,
                    "source_refs": [
                        {
                            "page": 1,
                            "line_start": len(lines),
                            "line_end": len(lines),
                            "quote": question["text"],
                        }
                    ],
                }
            )
        case = {
            "id": scope["case_id"],
            "pages": [
                {"number": 1, "text": "\n".join(lines), "method": "native", "needs_review": False}
            ],
            "identification": {
                "subject": fixture["title"],
                "document_date": "2026-11-17",
                "requests": requests,
            },
        }
        for request in build_source_requests(
            case, allowed_collection_ids=scope["allowed_collection_ids"]
        ):
            request["request_intent"] = classify_request_intent(request)
            results[fixture["id"] + "-" + request["id"]] = request
    for identifier in ("P2", "P4"):
        if identifier in saved:
            results["REG-" + identifier] = saved[identifier]
    return results


def source_catalog(scope):
    from pqrs_claro.source_library import SourceLibrary

    class ReadOnlyCatalog:
        @contextmanager
        def connect(self):
            with closing(
                sqlite3.connect((ROOT / "data/biblioteca.sqlite").as_uri() + "?mode=ro", uri=True)
            ) as connection:
                connection.execute("PRAGMA query_only=ON")
                yield connection

    return SourceLibrary.scoped(ReadOnlyCatalog(), scope["case_id"])


def run_retrieval(
    output, chunks, terms, scope, manifest, saved, content, rubric, only, baseline_results=None
):
    from pqrs_claro import source_retrieval as candidate
    from pqrs_claro import source_semantic

    baseline = baseline_module("source_retrieval")
    baseline_index, semantic, setup = prepare_runtime(
        chunks, terms, COMMON / "profile", semantic_module=source_semantic
    )
    candidate_index = candidate.RetrievalIndex(chunks, prepared_terms=terms)
    requests = fixture_requests(content, scope, saved)
    all_originals = {row["chunk_id"]: row for row in chunks}
    rows = []
    for number, (key, request) in enumerate(requests.items()):
        if only and key not in only:
            continue
        case_id, request_id = key.rsplit("-", 1)
        rule = rubric["cases"].get(case_id, {}).get(request_id, {})
        variants = ["master", "candidate"] if number % 2 == 0 else ["candidate", "master"]
        result = {"key": key, "request": request, "variants": {}}
        for variant in variants:
            if variant == "master" and baseline_results is not None:
                previous = read(baseline_results / "retrieval" / (key + ".json"))
                assert previous["request"] == request
                assert (
                    read(baseline_results / "retrieval-summary.json")["corpus_sha256"]
                    == (manifest["corpus_sha256"])
                )
                result["variants"][variant] = {
                    **previous["variants"][variant],
                    "reused_offline_baseline": True,
                }
                result["variants"][variant]["obligations"] = obligations(
                    rule, result["variants"][variant]["candidates"]
                )
                continue
            # Both modes encode this query once, with the resident model. Matrix,
            # document statistics and lexical caches warm naturally across questions.
            semantic._queries.clear()
            select = baseline.retrieve if variant == "master" else candidate.retrieve
            index = baseline_index if variant == "master" else candidate_index
            started = time.perf_counter()
            selected = select(request, chunks, index=index, semantic=semantic)
            seconds = time.perf_counter() - started
            assert len(selected) <= 24 and len({c["chunk_id"] for c in selected}) == len(selected)
            for source in selected:
                original = all_originals[source["chunk_id"]]
                assert all(
                    source.get(field) == original.get(field)
                    for field in (
                        "source_id",
                        "document_id",
                        "version",
                        "sha256",
                        "extraction_revision",
                        "quote",
                        "page",
                        "line_start",
                        "line_end",
                        "case_id",
                        "collection_id",
                        "method",
                        "needs_review",
                        "review_status",
                    )
                ), source["chunk_id"]
                assert candidate.source_in_scope(request, source)
            result["variants"][variant] = {
                "retrieval_seconds": seconds,
                "candidates": selected,
                "obligations": obligations(rule, selected),
                "lexical": dict(index.diagnostics),
                "semantic": dict(semantic.diagnostics),
            }
            print(
                key,
                variant,
                round(seconds, 3),
                result["variants"][variant]["obligations"],
                flush=True,
            )
        old = {c["chunk_id"] for c in result["variants"]["master"]["candidates"]}
        new = {c["chunk_id"] for c in result["variants"]["candidate"]["candidates"]}
        result["removed"] = sorted(old - new)
        result["added"] = sorted(new - old)
        save(output / "retrieval" / (key + ".json"), result)
        rows.append(
            {
                "key": key,
                **{
                    v: {k: item[k] for k in ("retrieval_seconds", "obligations")}
                    for v, item in result["variants"].items()
                },
            }
        )
    save(
        output / "retrieval-summary.json",
        {
            "corpus_sha256": manifest["corpus_sha256"],
            "sources": manifest["source_count"],
            "chunks": len(chunks),
            "setup": setup,
            "rows": rows,
            "method": (
                "Same sealed corpus and questions; master results/timings reused from the "
                "previous run. Candidate timed independently with a prepared semantic index."
                if baseline_results is not None else
                "Alternating order within one process; prepared semantic cache and model shared, "
                "separate lexical indexes, query embedding reset for each variant."
            ) + " First use includes lazy index initialization. Retrieval only.",
        },
    )


def run_reader(output, chunks, terms, scope, manifest, only):
    from pqrs_claro import source_retrieval, source_semantic
    from pqrs_claro.config import Settings
    from pqrs_claro.evidence_contract import apply_evidence_contract, catalog_audit, group_checks
    from pqrs_claro.performance_metrics import operation
    from pqrs_claro.source_assessment import OpenAISourceAssessor

    settings = Settings.load()
    catalog = source_catalog(scope)
    assessor = OpenAISourceAssessor(
        settings.api_key, settings.model, service_tier=settings.source_service_tier
    )
    sealed = read(output / "code-seal.json")
    assert all(sha(ROOT / file) == digest for file, digest in sealed.items()), (
        "Code changed after selection"
    )
    assert read(output / "retrieval-summary.json")["corpus_sha256"] == manifest["corpus_sha256"]
    inputs = {p.name: sha(p) for p in sorted((output / "retrieval").glob("*.json"))}
    reader_seal = {
        "code": sealed,
        "input_files": inputs,
        "model": settings.model,
        "tier": settings.source_service_tier,
        "corpus": manifest["corpus_sha256"],
    }
    seal_path = output / "reader-input-seal.json"
    if seal_path.exists():
        assert read(seal_path) == reader_seal
    else:
        save(seal_path, reader_seal)
    data = output / "reader-data"
    jobs = []
    for number, path in enumerate(sorted((output / "retrieval").glob("*.json"))):
        row = read(path)
        if only and row["key"] not in only:
            continue
        for variant in ["master", "candidate"] if number % 2 == 0 else ["candidate", "master"]:
            jobs.append((row, variant))
    assert len(jobs) <= 32, "Bounded A/B round: maximum 16 questions times 2 modes"
    baseline = baseline_module("source_retrieval")
    old_index, semantic, setup = prepare_runtime(
        chunks, terms, COMMON / "profile", semantic_module=source_semantic
    )
    indices = {
        "master": old_index,
        "candidate": source_retrieval.RetrievalIndex(chunks, prepared_terms=terms),
    }
    selectors = {"master": baseline.retrieve, "candidate": source_retrieval.retrieve}
    retrieve_lock = threading.Lock()
    warm_started = time.perf_counter()
    for variant in selectors:
        selectors[variant](jobs[0][0]["request"], chunks, index=indices[variant], semantic=semantic)
    setup["initial_statistics_warmup_seconds"] = time.perf_counter() - warm_started

    def evaluate(job):
        row, variant, batch_started = job
        target = output / "reader" / (row["key"] + "-" + variant + ".json")
        if target.exists():
            return {**read(target), "reused": True}
        metric_id = row["key"] + "-" + variant
        (data / "files" / metric_id).mkdir(parents=True, exist_ok=True)
        request = row["request"]
        started = time.perf_counter()
        result = {"key": row["key"], "variant": variant, "reused": False}
        with operation(
            "full_library_reader", root=data, case_id=metric_id, request_id=request["id"]
        ):
            try:
                with retrieve_lock:
                    retrieval_started = time.perf_counter()
                    selected = selectors[variant](
                        request, chunks, index=indices[variant], semantic=semantic
                    )
                    result["retrieval_seconds"] = time.perf_counter() - retrieval_started
                    expected = row["variants"][variant]["candidates"]
                    assert [(c["chunk_id"], c["quote"]) for c in selected] == [
                        (c["chunk_id"], c["quote"]) for c in expected
                    ], "Candidate identity/order changed since offline gate"
                    assert all(
                        all(
                            actual.get(field) == old.get(field)
                            for field in (
                                "source_id",
                                "document_id",
                                "version",
                                "sha256",
                                "extraction_revision",
                                "page",
                                "line_start",
                                "line_end",
                                "case_id",
                                "collection_id",
                                "method",
                                "needs_review",
                                "review_status",
                                "category",
                                "validity",
                                "document_status",
                                "verification_status",
                                "extraction_status",
                                "origin",
                            )
                        )
                        for actual, old in zip(selected, expected)
                    )
                reading_started = time.perf_counter()
                finding = assessor.assess(request, selected)
                validated_at = time.perf_counter()
                scoped = catalog_audit(request, finding, catalog, chunks=chunks)
                finding = apply_evidence_contract(scoped, finding)
                citation_count = sum(
                    len(c.get("citations", []))
                    for c in finding.get("sufficiency", {}).get("coverage", [])
                )
                result.update(
                    finding=finding,
                    reader_citation_seconds=validated_at - reading_started,
                    catalog_contract_seconds=time.perf_counter() - validated_at,
                    local_queue_seconds=retrieval_started - started,
                    until_result_seconds=time.perf_counter() - batch_started,
                    citation_count=citation_count,
                    until_validated_seconds=(
                        time.perf_counter() - batch_started if citation_count else None
                    ),
                )
            except Exception as error:
                result["error_type"] = type(error).__name__
        result["worker_total_seconds"] = time.perf_counter() - started
        save(target, result)
        print(
            row["key"],
            variant,
            round(result["worker_total_seconds"], 3),
            result.get("error_type", result.get("finding", {}).get("status")),
            flush=True,
        )
        return result

    start = time.perf_counter()
    groups = {}
    for row, variant in jobs:
        groups.setdefault(row["key"].rsplit("-", 1)[0], {}).setdefault(variant, []).append(row)
    results, batches = [], []
    for position, (case, variants) in enumerate(groups.items()):
        for variant in ["master", "candidate"] if position % 2 == 0 else ["candidate", "master"]:
            semantic._queries.clear()
            batch_started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=5) as pool:
                batch_results = list(
                    pool.map(evaluate, [(row, variant, batch_started) for row in variants[variant]])
                )
                results.extend(batch_results)
            batches.append(
                {
                    "case": case,
                    "variant": variant,
                    "seconds": time.perf_counter() - batch_started,
                    "reused_results": sum(r["reused"] for r in batch_results),
                    "fresh_timing": not any(r["reused"] for r in batch_results),
                    "shared_checks": group_checks(
                        [r["finding"] for r in batch_results if "finding" in r]
                    ),
                }
            )
    save(
        output / "reader-summary.json",
        {
            "model": settings.model,
            "tier": settings.source_service_tier,
            "corpus_sha256": manifest["corpus_sha256"],
            "reader_batch_wall_seconds": time.perf_counter() - start,
            "jobs": len(jobs),
            "runtime_setup": setup,
            "batches": batches,
            "errors": sum("error_type" in row for row in results),
            "median_worker_seconds": statistics.median(
                row["worker_total_seconds"] for row in results
            ),
            "note": "Prepared index, serial retrieval, up to five readers per case."
            " Wall time includes citation validation and contract; no drafting or delivery.",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=COMMON / "round-1")
    parser.add_argument("--run-api", action="store_true")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--baseline-results", type=Path)
    suites = parser.add_mutually_exclusive_group()
    suites.add_argument("--holdout", action="store_true",
                        help="Use only the independently sealed additional cases.")
    suites.add_argument("--all-cases", action="store_true",
                        help="Run the original and additional cases on the same prepared index.")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    fixtures = ROOT / "tests/fixtures"
    prefix = "full_library_retrieval_holdout" if args.holdout else "full_library_retrieval"
    content_path = fixtures / (prefix + "_content.json")
    rubric_path = fixtures / (prefix + "_rubric.json")
    regression_path = ROOT / "tests/fixtures/full_library_retrieval_regressions.json"
    inputs = [content_path, rubric_path]
    if not args.holdout:
        inputs.append(regression_path)
    extra_content = fixtures / "full_library_retrieval_holdout_content.json"
    extra_rubric = fixtures / "full_library_retrieval_holdout_rubric.json"
    if args.all_cases:
        inputs.extend((extra_content, extra_rubric))
    fixture_seal = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    args.output.mkdir(parents=True, exist_ok=True)
    seal = args.output / "fixtures-seal.json"
    if seal.exists():
        assert read(seal) == fixture_seal
    else:
        save(seal, fixture_seal)
    if not args.run_api:
        code_seal = {
            str(p.relative_to(ROOT)): sha(p) for p in (ROOT / "src/pqrs_claro").glob("*.py")
        }
        previous = args.output / "code-seal.json"
        if previous.exists():
            assert read(previous) == code_seal, "Use a new round directory after code changes"
        save(previous, code_seal)
    chunks, terms, scope, manifest, saved = load_full_library(COMMON / "profile")
    if args.run_api:
        run_reader(args.output, chunks, terms, scope, manifest, args.only)
    else:
        content = read(content_path)
        rubric = read(rubric_path)
        if args.holdout:
            saved = {}
        else:
            rubric["cases"].update(read(regression_path)["cases"])
        if args.all_cases:
            content["cases"].extend(read(extra_content)["cases"])
            rubric["cases"].update(read(extra_rubric)["cases"])
        run_retrieval(
            args.output,
            chunks,
            terms,
            scope,
            manifest,
            saved,
            content,
            rubric,
            args.only,
            args.baseline_results,
        )


if __name__ == "__main__":
    main()
