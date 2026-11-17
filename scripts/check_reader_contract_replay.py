"""Replay captured reader responses through normal assessment, without network.

Creates a new isolated source run compatible with check_request_trace_generalization
--draft-from-run. Original API responses, requests, retrieval candidates and data are
immutable. This is local contract validation, not another model evaluation or a
new end-to-end performance measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import time
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from check_request_trace_generalization import citations, code_hashes, save, sha

PROJECT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def immutable_inputs(run):
    """Hash test evidence/data, excluding large unchanged model binaries."""
    return {
        str(path.relative_to(run)): sha(path)
        for path in sorted(run.rglob("*"))
        if path.is_file() and not path.is_relative_to(run / "data/semantic/models")
    }


def captured_calls(run):
    calls, omitted = {}, []
    for path in sorted((run / "api").glob("*-request.json")):
        value = read(path)
        scope = value["scope"]
        response_path = path.with_name(path.name.replace("-request", "-response"))
        if scope["stage"] != "sources":
            omitted.append({
                "scope": scope,
                "request_file": str(path),
                "request_sha256": sha(path),
                "response_file": str(response_path),
                "response_sha256": sha(response_path) if response_path.exists() else None,
            })
            continue
        response = read(response_path)
        assert response["ok"] and response["response"]["status"] == "completed"
        payload = json.loads(value["request"]["input"])
        output = "".join(
            c.get("text", "")
            for item in response["response"]["output"]
            for c in item.get("content", [])
            if c["type"] == "output_text"
        )
        calls.setdefault((scope["case_id"], scope["request_id"]), []).append(
            {
                "request_file": str(path),
                "response_file": str(response_path),
                "request_sha256": sha(path),
                "response_sha256": sha(response_path),
                "payload": payload,
                "selection": json.loads(output),
                "instructions_sha256": digest(value["request"]["instructions"]),
                "model": value["request"]["model"],
            }
        )
    return calls, omitted


def compact_control(item):
    keys = (
        "check_key",
        "description",
        "original_description",
        "reason_code",
        "stage",
        "blocks_approval",
        "resolution",
        "linked_source_ids",
        "linked_chunk_ids",
        "source_versions",
        "separated_fulfillment",
        "affected_claim",
    )
    return {key: item[key] for key in keys if key in item}


def replay(args):
    from pqrs_claro import source_assessment
    from pqrs_claro.config import Settings
    from pqrs_claro.evidence_contract import apply_evidence_contract, catalog_audit, group_checks
    from pqrs_claro.extraction import PDFExtractor
    from pqrs_claro.source_library import SourceLibrary
    from pqrs_claro.source_service import SourceService
    from pqrs_claro.storage import CaseStore, now

    original = args.replay_reader_from
    target = args.output / "runs" / args.variant
    assert not target.exists(), "Keep all existing runs immutable; choose another variant"
    previous = read(original / "state.json")
    assert previous["code_unchanged"] and previous["isolated_imports"]
    for name, expected in previous["fixture_hashes"].items():
        assert sha(args.output / name) == expected, "Sealed fixture changed"
    history_hashes = immutable_inputs(original)
    calls, omitted = captured_calls(original)
    assert calls, "The run has no captured source-reader calls"
    shutil.copytree(original / "data", target / "data")
    settings = Settings(
        data_dir=target / "data",
        api_key="offline-no-credentials",
        model=previous["model"],
        source_service_tier=previous["source_service_tier"],
        source_concurrency=5,
        draft_concurrency=3,
        procedure_scope_pilot=False,
    )
    cases = CaseStore(settings.data_dir)
    library = SourceLibrary(settings.data_dir, PDFExtractor())
    service = SourceService(settings, cases, library)
    state = {
        "code_root": str(args.code_root),
        "code_hashes": code_hashes(args.code_root),
        "fixture_hashes": previous["fixture_hashes"],
        "model": settings.model,
        "source_service_tier": settings.source_service_tier,
        "procedure_scope_pilot": False,
        "source_only": True,
        "rubric_sent_to_model": False,
        "identification_seeded": True,
        "api_calls": 0,
        "network_attempts": 0,
        "captured_responses_replayed": 0,
        "non_reader_calls_omitted": omitted,
        "reader_inference_repeated": False,
        "cases": {},
        "replayed_source_run": {
            "path": str(original),
            "state_sha256": sha(original / "state.json"),
            "source_only": previous["source_only"],
            "input_hashes": history_hashes,
        },
    }
    comparisons = []

    def no_network(*_args, **_kwargs):
        state["network_attempts"] += 1
        raise AssertionError("Network forbidden during captured reader replay")

    try:
        with (
            patch.object(socket.socket, "connect", no_network),
            patch.object(socket.socket, "connect_ex", no_network),
            patch.object(socket, "create_connection", no_network),
        ):
            for cid in previous["cases"]:
                started = time.perf_counter()
                original_view = read(original / cid / "sources.json")
                full_run = library.latest_run(cid)
                assert full_run["id"] == original_view["id"]
                assert full_run["results"] == original_view["results"]
                assert original_view["status"] == "ready" and not original_view.get("stale")
                retrievals = read(original / cid / "retrievals.json")
                catalog = service.catalog(cid)
                _sources, chunks = library.snapshot(cid)
                results = []
                for old_finding in original_view["results"]:
                    rid = old_finding["request_id"]
                    matching = [r for r in retrievals if r["request"]["id"] == rid]
                    assert len(matching) == 1, "Expected one captured retrieval for each request"
                    retrieval = matching[0]
                    request, candidates = (
                        deepcopy(retrieval["request"]),
                        deepcopy(retrieval["candidates"]),
                    )
                    request_before, candidates_before = digest(request), digest(candidates)
                    sequence = calls[cid, rid]
                    used = []

                    def recorded_parse(**kwargs):
                        assert len(used) < len(sequence), "Replay requires an uncaptured response"
                        captured = sequence[len(used)]
                        assert kwargs["model"] == captured["model"]
                        assert digest(kwargs["instructions"]) == captured["instructions_sha256"], (
                            "Reader instructions differ from the captured call"
                        )
                        assert json.loads(kwargs["input"]) == captured["payload"], (
                            "Assessment payload differs from the captured reader input"
                        )
                        parsed = kwargs["text_format"].model_validate(captured["selection"])
                        used.append(
                            {
                                key: value
                                for key, value in captured.items()
                                if key not in {"payload", "selection"}
                            }
                        )
                        state["captured_responses_replayed"] += 1
                        return SimpleNamespace(status="completed", output_parsed=parsed)

                    # The real assessor's normal validation, line resolution,
                    # repair loop and materialization run with a replay client.
                    assessor = source_assessment.OpenAISourceAssessor.__new__(
                        source_assessment.OpenAISourceAssessor
                    )
                    assessor.model, assessor.service_tier = (
                        settings.model,
                        settings.source_service_tier,
                    )
                    assessor.client = SimpleNamespace(
                        responses=SimpleNamespace(parse=recorded_parse)
                    )
                    finding = assessor.assess(request, candidates)
                    assert len(used) == len(sequence), "Replay consumed a different repair sequence"
                    # Same post-assessment steps as SourceService.evaluate_request.
                    scoped = catalog_audit(
                        request,
                        finding,
                        catalog,
                        chunks=chunks,
                        retrieval_error=full_run.get("retrieval_warning"),
                    )
                    finding = apply_evidence_contract(scoped, finding, applications=())
                    if full_run.get("retrieval_warning"):
                        finding["warnings"] = list(
                            dict.fromkeys(
                                [*finding.get("warnings", []), full_run["retrieval_warning"]]
                            )
                        )
                    unchanged = {
                        "request": request_before == digest(request),
                        "candidates": candidates_before == digest(candidates),
                        "supports": old_finding["supports"] == finding["supports"],
                        "coverage": old_finding["sufficiency"]["coverage"]
                        == finding["sufficiency"]["coverage"],
                        "requirements": old_finding["sufficiency"]["request_requirements"]
                        == finding["sufficiency"]["request_requirements"],
                        "requirement_checks": old_finding["sufficiency"]["requirement_checks"]
                        == finding["sufficiency"]["requirement_checks"],
                        "citation_locations": old_finding.get("citation_locations")
                        == finding.get("citation_locations"),
                    }
                    assert all(unchanged.values()), (cid, rid, unchanged)
                    comparisons.append(
                        {
                            "case_id": cid,
                            "request_id": rid,
                            "unchanged": unchanged,
                            "request_sha256": request_before,
                            "candidates_sha256": candidates_before,
                            "old_finding_sha256": digest(old_finding),
                            "new_finding_sha256": digest(finding),
                            "captured_calls": used,
                            "current_instructions_sha256": digest(source_assessment.INSTRUCTIONS),
                            "before": [compact_control(c) for c in old_finding.get("checks", [])],
                            "after": [compact_control(c) for c in finding["checks"]],
                        }
                    )
                    results.append(finding)
                derived = {
                    **deepcopy(full_run),
                    "id": uuid.uuid4().hex,
                    "results": results,
                    "shared_checks": group_checks(results),
                    "searched_at": now(),
                    "replayed_from_run_id": full_run["id"],
                    "offline_contract_replay": True,
                }
                library.save_run(derived)
                visible = service.get(cid, compact=True)
                assert visible["id"] == derived["id"] and visible["results"] == results
                assert visible["status"] == "ready" and not visible.get("stale")
                validations = citations(library, cid, visible)
                assert all(
                    all(row[key] for key in ("literal", "version", "hash", "permission"))
                    for row in validations
                )
                save(target / cid / "sources.json", visible)
                save(target / cid / "retrievals.json", retrievals)
                save(target / cid / "citations.json", validations)
                state["cases"][cid] = {
                    "source_status": visible["status"],
                    "source_seconds": None,
                    "citation_seconds": {},
                    "offline_replay_seconds": time.perf_counter() - started,
                    "replayed_from_run_id": full_run["id"],
                    "derived_run_id": derived["id"],
                }
                save(target / "state.json", state)
    finally:
        service.close()
        state["history_modified"] = immutable_inputs(original) != history_hashes
        state["code_unchanged"] = state["code_hashes"] == code_hashes(args.code_root)
        state["loaded_modules"] = {
            name: str(Path(module.__file__).resolve())
            for name, module in sys.modules.items()
            if name.startswith("pqrs_claro") and getattr(module, "__file__", None)
        }
        state["isolated_imports"] = all(
            Path(path).is_relative_to(args.code_root / "src")
            for path in state["loaded_modules"].values()
        )
        save(target / "control-comparison.json", comparisons)
        save(target / "state.json", state)
    assert not state["history_modified"] and state["code_unchanged"] and state["isolated_imports"]
    assert state["network_attempts"] == 0 and state["api_calls"] == 0
    assert len(comparisons) == len(calls)
    print(
        json.dumps(
            {
                "target": str(target),
                "api_calls": 0,
                "responses_replayed": state["captured_responses_replayed"],
                "questions": len(comparisons),
                "history_modified": False,
            },
            ensure_ascii=False,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-reader-from", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    args = parser.parse_args()
    for name in ("replay_reader_from", "code_root", "output"):
        setattr(args, name, getattr(args, name).resolve())
    assert args.output.is_relative_to(PROJECT / "output/qa")
    assert args.replay_reader_from.is_relative_to(PROJECT / "output/qa")
    assert args.variant.replace("-", "").replace("_", "").isalnum()
    assert (args.code_root / "src/pqrs_claro/source_assessment.py").is_file()
    sys.path.insert(0, str(args.code_root / "src"))
    sys.stdout.reconfigure(encoding="utf-8")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    replay(args)


if __name__ == "__main__":
    main()
