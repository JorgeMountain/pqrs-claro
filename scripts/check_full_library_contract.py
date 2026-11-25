"""Reproduce citation/pendings QA AFTER a full-library selection, without inference.

Pass the directory written by check_full_library_retrieval.py. Each rubric is used
only after loading the saved candidates. Prescribed selections exercise the real
assessor, passage resolution and local evidence contract. The output is written
to audited-contract-replay.json in that QA directory. Durations cover validation
of the prescribed response. --with-catalog additionally checks the service's
final evidence contract against the complete authorized snapshot, reporting to
audited-catalog-replay.json. No human applications are simulated. Both modes
exclude model inference, retrieval, persistence and presentation in the UI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from check_full_library_retrieval import read, save, sha, source_catalog
from profile_full_library_retrieval import COMMON, ROOT, load_full_library

from pqrs_claro.evidence_contract import apply_evidence_contract, catalog_audit
from pqrs_claro.source_assessment import (
    OpenAISourceAssessor,
    _allowed_roles,
    _LocatedSourceSelection,
)
from pqrs_claro.source_documents import requested_document
from pqrs_claro.source_library import make_chunks
from pqrs_claro.source_retrieval import source_in_scope

# Each list corresponds to one actual request requirement, in order. Names are
# independent rubric obligations. The selector and normal reader never access these.
REQUIREMENTS = {
    "FL-ADM-P2": [["all", "no_penalty"]],
    "FL-ACT-P2": [["convoke", "scope"]],
    "FL-PRA-P1": [["academic", "business"], ["sixteen", "business"]],
    "FL-NEG-P2": [["weighted"], ["weighted"]],
    "REG-P2": [["exam_dates"]],
    "REG-P4": [["credential_fields"]],
    "HO-ADM-P1": [
        ["registration_window"],
        ["registration_window"],
        ["payment_window"],
        ["payment_window"],
        ["registration_window", "payment_window"],
    ],
    "HO-PRE-P1": [
        ["places", "average", "certificate", "affinity"],
        ["places", "average", "certificate", "affinity", "authority"],
        ["authority"],
    ],
    "HO-PRA-P1": [
        ["credits", "induction", "program_requirements", "business_course", "study_plan"],
        ["business_course", "expiry"],
        ["refresh"],
    ],
    "HO-IND-P1": [["enrollment_condition"], ["enrollment_condition"], ["enrollment_condition"]],
}
PERSONAL_GAPS = {
    "FL-NEG-P2": "Obtener calificaciones parciales y final, con sus ponderaciones, o el registro "
    "académico oficial equivalente para calcular y certificar el resultado.",
    "HO-IND-P1": "Comprobar el asiento de matrícula de la persona en el registro académico del "
    "curso y periodo solicitados antes de confirmar que puede iniciar la práctica.",
}
REGRESSION_CLAIMS = {
    "exam_dates": "El calendario indicó el 26 y el 27 de octubre de 2026 para el examen.",
    "credential_fields": "La credencial enumera nombres y apellidos, número de credencial, año "
    "y semestre, programas, documento y clase, día, hora, bloque, aula, "
    "sede o campus y dirección.",
}


def verify_sources(request, candidates):
    """Abort if a stored result no longer matches the original, its version or ACL."""
    with closing(
        sqlite3.connect((ROOT / "data/biblioteca.sqlite").as_uri() + "?mode=ro", uri=True)
    ) as db:
        db.execute("BEGIN")
        acl = {
            row[0]
            for row in db.execute(
                "SELECT collection_id FROM case_source_collections WHERE case_id=?",
                (request["case_id"],),
            )
        }
        if acl != set(request["allowed_collection_ids"]):
            raise ValueError("Collection permissions changed since retrieval")
        originals = {}
        for sid in {row["source_id"] for row in candidates}:
            record = db.execute(
                "SELECT body,pages FROM sources s WHERE id=? AND version="
                "(SELECT MAX(version) FROM sources v WHERE v.document_id=s.document_id)",
                (sid,),
            ).fetchone()
            if not record:
                raise ValueError("Selected source was replaced or removed")
            body, pages = record
            source = {**json.loads(body), "is_latest": True}
            if not source_in_scope(request, source):
                raise ValueError("Source no longer in scope")
            path = (
                ROOT / "data/library" / sid / ("original" + Path(source["filename"]).suffix.lower())
            )
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != source["sha256"]:
                    raise ValueError("Original changed after extraction")
            originals.update({c["chunk_id"]: c for c in make_chunks(source, json.loads(pages))})
        for row in candidates:
            current = originals[row["chunk_id"]]
            if any(row.get(k) != v for k, v in current.items()):
                raise ValueError("Original passage or source metadata changed since retrieval")


def find_location(candidates, obligation):
    """Select an independently identified excerpt with matching source, page and literal words."""
    for alt in obligation["alternatives"]:
        for number, source in enumerate(candidates, 1):
            if (source["source_id"], source["page"]) != (alt["source_id"], alt["page"]):
                continue
            pattern = r"\s+".join(re.escape(word) for word in alt["quote"].split())
            match = re.search(pattern, source["quote"])
            if match:
                start = source["quote"][: match.start()].count("\n") + 1
                end = source["quote"][: match.end()].count("\n") + 1
                return source, {"chunk_id": f"C{number}", "line_start": start, "line_end": end}
    if obligation["id"] == "exam_dates":
        # Independently inspected secondary OCR table. Include the row labels,
        # order and dates; a cell containing two numbers is insufficient on its own.
        for number, source in enumerate(candidates, 1):
            if (
                source["chunk_id"] == "0736d9c8f4344cc08498568504a4c4b9:1:1:47"
                and source["method"] == "ocr"
            ):
                lines = source["quote"].splitlines()
                if "ARTICULO 1." in lines[25] and "26 y 27 de octubre" in lines[43]:
                    return source, {"chunk_id": f"C{number}", "line_start": 26, "line_end": 44}
    return None


def evaluate(key, variant, request, candidates, rule, snapshot=None):
    verify_sources(request, candidates)
    supports, coverage, missing, checks, locations = {}, {}, [], [], []
    for obligation in rule["required_alternatives"]:
        found = find_location(candidates, obligation)
        if not found:
            continue
        source, citation = found
        alias, aspect = citation["chunk_id"], obligation["id"]
        role = _allowed_roles(
            source["category"], requested_document(request), request=request, source=source
        )[0]
        supports[alias] = {
            "chunk_id": alias,
            "role": role,
            "reason": "El pasaje sustenta el contenido atribuido a este documento.",
        }
        claim = obligation.get("criterion") or REGRESSION_CLAIMS[aspect]
        coverage[aspect] = {
            "aspect": aspect,
            "claim": claim,
            "use": "attributed_content",
            "citations": [citation],
            "explanation": "La afirmación describe el texto del documento identificado.",
            "application": {
                "status": "not_requested",
                "uncertainty_indexes": [],
                "explanation": "La cita se limita al texto que contiene la regla.",
            },
        }
        locations.append(
            {
                "obligation": aspect,
                "source_id": source["source_id"],
                "page": source["page"],
                "method": source["method"],
                "needs_review": source["needs_review"],
                "chunk_id": source["chunk_id"],
                "start": citation["line_start"],
                "end": citation["line_end"],
            }
        )
    gaps = {}
    for req, aspects in zip(request["request_requirements"], REQUIREMENTS[key], strict=True):
        missing_aspects = [aspect for aspect in aspects if aspect not in coverage]
        descriptions = [
            "Localizar el pasaje que respalda el componente solicitado " + item
            for item in missing_aspects
        ]
        if key in PERSONAL_GAPS and req["id"] == "R1":
            descriptions.append(PERSONAL_GAPS[key])
        for description in descriptions:
            if description not in gaps:
                gaps[description] = len(missing)
                missing.append(
                    {
                        "kind": "fact",
                        "reason_code": "fact_confirmation",
                        "stage": "evidence",
                        "basis": "content_gap",
                        "source_chunk_ids": [],
                        "description": description,
                        "affected_claim": req["text"],
                        "why_unresolved": "Los respaldos evalúan lo descrito en la norma. "
                        "No acreditan el componente faltante.",
                    }
                )
        checks.append(
            {
                "requirement_id": req["id"],
                "status": "pending" if descriptions else "supported",
                "coverage_indexes": [list(coverage).index(a) for a in aspects if a in coverage],
                "missing_indexes": [gaps[d] for d in descriptions],
                "uncertainty_indexes": [],
                "explanation": "Contraste con el pasaje disponible y con el alcance solicitado.",
            }
        )
    if key == "REG-P2" and locations and locations[0]["needs_review"]:
        missing.append(
            {
                "kind": "fact",
                "reason_code": "transcription",
                "stage": "evidence",
                "basis": "content_gap",
                "source_chunk_ids": list(supports),
                "description": "Cotejar en el PDF original la transcripción OCR de las "
                "fechas del examen de admisión.",
                "affected_claim": "Fechas del examen.",
                "why_unresolved": "La tabla proviene de OCR pendiente de cotejo.",
            }
        )
    selection = _LocatedSourceSelection.model_validate(
        {
            "status": "needs_evidence" if missing else "references_found",
            "missing": missing,
            "summary": "Evaluación controlada para comprobar las reglas locales.",
            "supports": list(supports.values()),
            "warnings": [],
            "coverage": list(coverage.values()),
            "coverage_complete": all(c["status"] == "supported" for c in checks),
            "requirement_checks": checks,
        }
    )
    assessor = object.__new__(OpenAISourceAssessor)
    assessor.model = "prescribed-local-selection"
    assessor.service_tier = "default"
    assessor.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **_: SimpleNamespace(status="completed", output_parsed=selection)
        )
    )
    started = perf_counter()
    finding = assessor.assess(request, candidates)
    validated = perf_counter()
    catalog_result = {}
    if snapshot is not None:
        catalog, chunks = snapshot
        scoped = catalog_audit(request, finding, catalog, chunks=chunks, retrieval_error=None)
        audited = perf_counter()
        final = apply_evidence_contract(scoped, finding, applications=())
        finished = perf_counter()
        search = scoped["search_audit"]
        catalog_result = {
            "catalog_seconds": audited - validated,
            "post_catalog_contract_seconds": finished - audited,
            "catalog_entries_in_scope": search["catalog_count"],
            "unread_source_count": len(search["unread_source_ids"]),
            "full_catalog_text_search": search["full_catalog_text_search"],
            "targeted_reference_count": len(search["targeted_references"]),
            "reader_checks_preserved": finding["checks"] == final["checks"],
            "reader_evidence_preserved": all(
                finding[k] == final[k] for k in ("supports", "sufficiency", "verifications")
            ),
        }
        finding = final
    return {
        "key": key,
        "variant": variant,
        "validation_seconds": validated - started,
        **catalog_result,
        "locations": locations,
        "candidate_count": len(candidates),
        "citations": sum(len(c["citations"]) for c in finding["sufficiency"]["coverage"]),
        "missing": [
            {
                "reason": c["reason_code"],
                "description": c["description"],
                "blocks_approval": c["blocks_approval"],
            }
            for c in finding["missing"]
        ],
        "actions": [c["description"] for c in finding["actions"]],
        "coverage_complete": finding["sufficiency"]["coverage_complete"],
        "audit": finding["analysis_diagnostic"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round", type=Path)
    parser.add_argument(
        "--with-catalog",
        action="store_true",
        help="Check the final contract using the entire local snapshot",
    )
    parser.add_argument(
        "--require-candidate",
        action="store_true",
        help="Fail on a missing rubric citation, unintended check or lost individual check",
    )
    args = parser.parse_args()
    rules = {}
    for fixture in ("rubric", "regressions", "holdout_rubric"):
        rules.update(
            read(ROOT / "tests/fixtures" / f"full_library_retrieval_{fixture}.json")["cases"]
        )
    summary = read(args.round / "retrieval-summary.json")
    snapshot, setup = None, {}
    if args.with_catalog:
        started = perf_counter()
        chunks, terms, scope, manifest, _ = load_full_library(COMMON / "profile")
        del terms
        if (manifest["corpus_sha256"], len(chunks)) != (
            summary["corpus_sha256"],
            summary["chunks"],
        ):
            raise ValueError("Corpus changed after retrieval")
        snapshot = source_catalog(scope), chunks
        setup = {
            "snapshot_read_seconds": perf_counter() - started,
            "eligible_chunks": len(chunks),
            "catalog_rows": len(snapshot[0]),
            "human_applications": 0,
        }
    expected_keys = set(REQUIREMENTS).intersection(row["key"] for row in summary["rows"])
    if not expected_keys:
        raise ValueError("No configured QA queries in this retrieval round")
    results, hashes = [], {}
    for key in sorted(expected_keys):
        case, question = key.rsplit("-", 1)
        rule = rules[case][question]
        path = args.round / "retrieval" / (key + ".json")
        hashes[key] = sha(path)
        row = read(path)
        if row["key"] != key:
            raise ValueError("Mismatched retrieval file")
        for variant, record in row["variants"].items():
            results.append(
                evaluate(key, variant, row["request"], record["candidates"], rule, snapshot)
            )
        if key == "REG-P2":
            guide_ids = {
                alt["source_id"]
                for group in rule["required_alternatives"]
                for alt in group["alternatives"]
            }
            filtered = [
                s
                for s in row["variants"]["candidate"]["candidates"]
                if s["source_id"] not in guide_ids
            ]
            results.append(
                evaluate(
                    key, "candidate_without_native_guide", row["request"], filtered, rule, snapshot
                )
            )
    issues = []
    for row in results:
        if snapshot and not row["reader_evidence_preserved"]:
            issues.append(
                {
                    "key": row["key"],
                    "variant": row["variant"],
                    "issue": "Catalog changed cited evidence",
                }
            )
        if row["variant"] == "master":
            continue
        key = row["key"]
        expected = {name for requirement in REQUIREMENTS[key] for name in requirement}
        found = {location["obligation"] for location in row["locations"]}
        reasons = [check["reason"] for check in row["missing"]]
        if found != expected:
            issues.append(
                {
                    "key": key,
                    "variant": row["variant"],
                    "missing_citations": sorted(expected - found),
                }
            )
        if key in PERSONAL_GAPS:
            descriptions = [check["description"] for check in row["missing"]]
            if (
                descriptions.count(PERSONAL_GAPS[key]) != 1
                or row["coverage_complete"]
                or len(reasons) != len(set(reasons))
            ):
                issues.append({"key": key, "issue": "Individual evidence check lost or duplicated"})
            if any(
                reason not in {"fact_confirmation", "provenance", "validity"} for reason in reasons
            ):
                issues.append(
                    {"key": key, "issue": "Unexpected individual check", "reasons": reasons}
                )
            continue
        review_pages = {(r["source_id"], r["page"]) for r in row["locations"] if r["needs_review"]}
        if sorted(reasons) != ["transcription"] * len(review_pages):
            issues.append({"key": key, "variant": row["variant"], "unexpected_checks": reasons})
    save(
        args.round
        / ("audited-catalog-replay.json" if args.with_catalog else "audited-contract-replay.json"),
        {
            "mode": "Prescribed reader selection. Production citation and local evidence checks.",
            "corpus_sha256": summary["corpus_sha256"],
            "catalog_setup": setup,
            "retrieval_input_sha256": hashes,
            "contract_code_sha256": {
                name: sha(ROOT / "src/pqrs_claro" / (name + ".py"))
                for name in ("evidence_contract", "source_assessment", "source_sufficiency")
            },
            "controlled_candidate_issues": issues,
            "results": results,
        },
    )
    for row in results:
        print(row["key"], row["variant"], row["citations"], [c["reason"] for c in row["missing"]])
    if args.require_candidate and issues:
        raise SystemExit(f"{len(issues)} issues in controlled candidate evaluations")


if __name__ == "__main__":
    main()
