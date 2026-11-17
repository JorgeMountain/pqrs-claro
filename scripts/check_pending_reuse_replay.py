"""Offline replay of fictional pending controls against two isolated code roots.

No API calls, live cases, or source files are changed. This measures normalization
and serialized base-context bytes; it does not measure LLM quality or API tokens.
The baseline already reused explicit references inside DraftEngine._pending.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def fixture():
    request = {
        "id": "REPLAY-P1", "case_id": "fictional-pending-replay",
        "title": "Informe de calibración del laboratorio escolar",
        "description": "Confirme firma, competencia e integridad del informe de calibración.",
        "context": {"setting": "Laboratorio escolar ficticio de óptica"},
        "allowed_collection_ids": ["fictional-replay"],
    }
    source = {
        "source_id": "fixture-optics-v1", "document_id": "fixture-optics",
        "version": 1, "sha256": "a" * 64, "extraction_revision": 1,
        "title": "Informe de calibración 781 de 2026", "filename": "calibracion-781.pdf",
        "collection_id": "fictional-replay", "category": "historical_response",
        "document_status": "issued", "extraction_status": "ready", "role": "antecedent",
        "chunk_id": "fixture-optics-v1:1:1:3", "page": 1, "line_start": 1, "line_end": 3,
        "quote": "El informe registra la calibración del telescopio escolar.\n"
                 "Firma: responsable de laboratorio.\nResultados: véase el anexo técnico.",
    }
    controls = [{
        "kind": "fact", "reason_code": "fact_confirmation", "basis": "content_gap",
        "description": description, "affected_claim": claim, "why_unresolved": gap,
        "linked_source_ids": [source["source_id"]],
        "linked_chunk_ids": [source["chunk_id"]],
    } for description, claim, gap in [
        ("Cotejar la identidad del firmante del informe.",
         "La firma pertenece al responsable del laboratorio.",
         "El texto no identifica nominalmente al firmante."),
        ("Confirmar la competencia de quien autorizó la calibración.",
         "El firmante estaba facultado para autorizar la calibración.",
         "El informe no contiene la designación o delegación."),
        ("Cotejar la integridad del anexo de resultados.",
         "El anexo conserva todos los resultados de la calibración.",
         "El texto remite al anexo sin describir su integridad."),
    ]]
    return request, source, controls


def application(request, source, check):
    record = {
        "id": "fictional-review", "kind": "human_review", "recording_method": "human_form",
        "fact": check["affected_claim"], "basis": "Cotejo simulado para probar el contrato.",
        "recorded_by": "Evaluador ficticio", "recorded_at": "2026-11-17T00:00:00Z",
        "case_id": request["case_id"], "source_id": source["source_id"],
        "document_id": source["document_id"], "version": source["version"],
        "source_sha256": source["sha256"], "extraction_revision": source["extraction_revision"],
        "passage": {key: source[key] for key in
                    ("chunk_id", "page", "line_start", "line_end", "quote")},
    }
    return {
        "id": "fictional-application", "verification_id": record["id"], "record": record,
        "case_id": request["case_id"], "check_key": check["check_key"],
        "request_ids": [request["id"]], "scope_key": check["scope_key"],
        "check_reason": check["reason_code"], "basis": record["basis"],
    }


def worker(code_root):
    evidence = importlib.import_module("pqrs_claro.evidence_contract")
    draft = importlib.import_module("pqrs_claro.draft_engine")
    for module in (evidence, draft):
        assert Path(module.__file__).resolve().is_relative_to(code_root / "src"), module.__file__
    request, source, controls = fixture()

    def finding(selected):
        return evidence.apply_evidence_contract(request, {
            "request_id": request["id"], "status": "needs_evidence", "supports": [source],
            "missing": deepcopy(selected), "warnings": [],
        })

    initial = finding(controls[:1])
    check = initial["checks"][0]
    reference = {
        "kind": "fact", "description": "Corroborar quién suscribió el informe de calibración.",
        "existing_check_keys": [check["check_key"]],
    }
    reviewed = evidence.apply_evidence_contract(
        request, initial, applications=[application(request, source, check)],
    )
    assert reviewed["checks"][0]["resolution"]["status"] == "resolved"
    only_registry = {**deepcopy(initial), "missing": [], "actions": []}
    changed = evidence.apply_evidence_contract(request, {
        **deepcopy(initial), "supports": [{**source, "version": 2, "sha256": "b" * 64}],
    }, applications=[application(request, source, check)])
    revoked = evidence.apply_evidence_contract(request, {
        **deepcopy(initial), "supports": [], "candidate_documents": [],
    }, applications=[application(request, source, check)])
    scenarios = [
        ("referenced_open_paraphrase", initial, [reference], 1),
        ("open_control_only_in_registry", only_registry, [], 1),
        ("signature_and_authority_remain_distinct", finding(controls[:2]), [], 2),
        ("referenced_resolved_paraphrase", reviewed, [reference], 0),
        ("changed_version_reopens_control", changed, [], 1),
        ("withdrawn_source_does_not_reuse_review", revoked, [], 1),
    ]
    results = []
    for name, current, proposed, expected in scenarios:
        before = digest(current)
        pending = evidence.normalize_pending(request, current, proposed)
        repeated = evidence.normalize_pending(request, current, pending)
        row = {
            "case": name, "expected_open_controls": expected,
            "normalizer_open_controls": len(pending), "normalizer_matches_expected":
            len(pending) == expected, "pending": pending,
            "idempotent": repeated == pending,
            "source_payload_sha256": digest(current["supports"]),
            "finding_unchanged": digest(current) == before,
            "finding_sha256": before,
        }
        # Deliberately distinguish the pre-existing DraftEngine suppression from
        # the general normalizer. Revoked-source drafting adds a legitimate
        # search task and is outside this normalization comparison.
        if current["supports"]:
            row["draft_engine_open_controls"] = len(draft._pending(request, current, proposed))
        results.append(row)

    context_finding = finding(controls)
    context_finding = evidence.apply_evidence_contract(request, context_finding, applications=[
        application(request, source, context_finding["checks"][2]),
    ])
    context, _ = draft._api_context(request, context_finding, {source["chunk_id"]: source})
    keys = {row["check_key"] for row in context_finding["checks"]}

    def occurrences(value):
        if isinstance(value, dict):
            return int(value.get("check_key") in keys) + sum(occurrences(v) for v in value.values())
        return sum(occurrences(v) for v in value) if isinstance(value, list) else 0

    return {
        "code_root": str(code_root), "api_calls": 0,
        "fixture_sha256": digest(fixture()), "cases": results,
        "code_hashes": {
            str(path.relative_to(code_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((code_root / "src/pqrs_claro").rglob("*.py"))
        },
        "base_context": {
            "utf8_bytes": len(encoded(context)), "sha256": digest(context),
            "control_record_occurrences": occurrences(context),
            "unique_control_count": len(keys),
            "registry_states": [row["resolution"]["status"]
                                for row in context["existing_pending"]],
            "supports_sha256": digest(context["finding"]["supports"]),
            "finding_sha256": digest(context_finding),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path, default=PROJECT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker.resolve()), ensure_ascii=False))
        return
    if not args.baseline or not args.output:
        parser.error("--baseline and --output are required")
    variants = {}
    for label, root in (("baseline", args.baseline), ("candidate", args.candidate)):
        root = root.resolve()
        assert (root / "src/pqrs_claro/evidence_contract.py").is_file(), root
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        run = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(root)],
            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", check=True,
        )
        variants[label] = json.loads(run.stdout)
    baseline, candidate = variants["baseline"], variants["candidate"]
    assert baseline["fixture_sha256"] == candidate["fixture_sha256"]
    assert baseline["base_context"]["finding_sha256"] == candidate["base_context"]["finding_sha256"]
    assert (baseline["base_context"]["supports_sha256"]
            == candidate["base_context"]["supports_sha256"])
    for old, new in zip(baseline["cases"], candidate["cases"], strict=True):
        assert old["case"] == new["case"] and old["finding_sha256"] == new["finding_sha256"]
        assert old["source_payload_sha256"] == new["source_payload_sha256"]
        assert new["normalizer_matches_expected"] and new["idempotent"] and new["finding_unchanged"]
    old_bytes = baseline["base_context"]["utf8_bytes"]
    new_bytes = candidate["base_context"]["utf8_bytes"]
    report = {
        "at": datetime.now(timezone.utc).isoformat(), "api_calls": 0,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "method": "Offline synthetic replay; same frozen input in isolated subprocesses.",
        "limits": [
            "Six engineered fixtures, not an LLM quality benchmark or new PDF extraction test.",
            "Master already suppresses referenced paraphrases inside DraftEngine._pending.",
            "Bytes cover base context only, not model tokens, prompts, or checker draft output.",
            "Withdrawal fixture removes authorized source payload; it does not invoke the ACL API.",
        ],
        "variants": variants,
        "base_context_byte_reduction": old_bytes - new_bytes,
        "base_context_byte_reduction_percent": round((old_bytes - new_bytes) * 100 / old_bytes, 2),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output), "api_calls": 0,
        "normalizer_counts": {label: [row["normalizer_open_controls"] for row in value["cases"]]
                              for label, value in variants.items()},
        "base_context_bytes": {label: value["base_context"]["utf8_bytes"]
                               for label, value in variants.items()},
        "base_context_byte_reduction_percent": report["base_context_byte_reduction_percent"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
