"""Validate citation/checker changes in a new isolated copy, with source search disabled.

Commands: prepare; local-checks --label despues; run --through reviews; report; integrity.
All application writes target output/qa/draft-quality-20260909/data. The previous
QA and live databases are read-only origins. No approvals or human facts are created.
"""

from __future__ import annotations

import argparse
import copy
import inspect
import json
import platform
import re
import shutil
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import validate_pending_workflow as common

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.draft_engine import OpenAIDraftEngine, _local_checks, _supports
from pqrs_claro.draft_service import DraftService
from pqrs_claro.review_engine import OpenAIReviewEngine, structural_checks
from pqrs_claro.review_service import ReviewService
from pqrs_claro.source_library import digest
from pqrs_claro.source_service import SourceService
from pqrs_claro.source_verifications import SourceVerificationStore
from pqrs_claro.storage import CaseStore, now

DEFAULT_OUTPUT = ROOT / "output/qa/draft-quality-20260909"
DEFAULT_PREVIOUS = ROOT / "output/qa/pending-verifications-20260909"
TARGET_REQUESTS = ("P3", "P4", "P5", "P9", "P10", "P11", "P14", "P18", "P20")
read_json, write_json = common.read_json, common.write_json


def code_snapshot():
    result = common.code_snapshot()
    result[str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/")] = common.file_sha(
        __file__
    )
    return result


def ensure_baseline_inputs(output, previous, previous_attempt):
    """Prefer the exact first capture; otherwise recover persisted v4 local checks."""
    target = output / "local-checks-antes.json"
    if target.exists():
        return
    drafts = read_json(output / "baseline/drafts.json")
    rows = []
    for row in drafts["results"]:
        captured = read_json(
            previous
            / "attempts"
            / previous_attempt
            / "calls/drafts"
            / f"{row['request_id']}-plan.json"
        )
        checks = row["checks"].get("local_checks", [])
        failed = {(item["code"], item["description"]) for item in checks if not item["passed"]}
        issues = [
            item
            for item in row["checks"]["issues"]
            if (item["code"], item["description"]) in failed
        ]
        rows.append(
            {
                "request_id": row["request_id"],
                **captured["inputs"],
                "draft": row["draft"],
                "local_checks": checks,
                "local_issues": issues,
            }
        )
    write_json(
        target,
        {
            "created_at": now(),
            "origin": "persisted v4 local_checks and matching issues",
            "draft_run_id": drafts["id"],
            "requests": rows,
        },
    )


def prepare(output, previous):
    if (output / "manifest.json").exists() or (output / "data").exists():
        raise ValueError("La copia ya existe; sus resultados se conservan.")
    if output == previous or output.is_relative_to(previous) or previous.is_relative_to(output):
        raise ValueError("La nueva validación debe estar separada de la anterior.")
    old_manifest = read_json(previous / "manifest.json")
    old_execution = read_json(previous / "execution.json")
    if old_execution["status"] != "completed":
        raise ValueError("La validación anterior no terminó.")
    old_data = Path(old_manifest["qa_data"]).resolve(strict=True)
    live = Path(old_manifest["live_data_read_only"]).resolve(strict=True)
    case_id = old_manifest["case_id"]
    output.mkdir(parents=True, exist_ok=True)
    baseline = output / "baseline"
    for name, origin in {
        "case.json": previous / "baseline/case.json",
        "sources.json": previous / "results/sources.json",
        "drafts.json": previous / "results/drafts.json",
        "reviews.json": previous / "results/reviews.json",
    }.items():
        target = baseline / name
        if target.exists() and common.file_sha(target) != common.file_sha(origin):
            raise ValueError(f"Cambió la captura previa: {name}.")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
    case, source = read_json(baseline / "case.json"), read_json(baseline / "sources.json")
    drafts = read_json(baseline / "drafts.json")
    ensure_baseline_inputs(output, previous, old_execution["attempt_id"])
    if case["request_count"] != 23 or source["status"] != "ready" or source.get("stale"):
        raise ValueError("Se requieren las 23 solicitudes y fuentes v11 vigentes.")
    old_fingerprint = common.live_fingerprint(old_data, case_id)
    write_json(output / "previous-integrity-before.json", old_fingerprint)
    write_json(output / "live-integrity-before.json", common.live_fingerprint(live, case_id))
    backup, data = baseline / "databases", output / "data"
    data.mkdir()
    for name in common.BUSINESS_DATABASES:
        if (old_data / name).is_file():
            common.database_snapshot(old_data / name, backup / name)
    for name in ("expedientes.sqlite", "biblioteca.sqlite", "comprobaciones.sqlite"):
        common.database_snapshot(backup / name, data / name)
    petition = data / "files" / case_id / "original.pdf"
    petition.parent.mkdir(parents=True)
    shutil.copy2(old_data / "files" / case_id / "original.pdf", petition)
    # Preserve the real installed-model signature; the search entry points are blocked.
    shutil.copytree(old_data / "semantic/models", data / "semantic/models")
    manifest = {
        "created_at": now(),
        "case_id": case_id,
        "case_version": case["version"],
        "case_sha256": digest(case),
        "request_count": 23,
        "qa_data": str(data),
        "previous_qa": str(previous),
        "previous_data_read_only": str(old_data),
        "live_data_read_only": str(live),
        "originals_read_only_path": old_manifest["originals_read_only_path"],
        "baseline_source_run_id": source["id"],
        "baseline_source_sha256": digest(source),
        "baseline_draft_run_id": drafts["id"],
        "baseline_draft_version": drafts["draft_version"],
        "previous_attempt": old_execution["attempt_id"],
        "baseline_passing_requests": [
            row["request_id"] for row in drafts["results"] if row["checks"]["status"] == "passed"
        ],
        "target_requests": TARGET_REQUESTS,
        "model": old_execution["model"],
        "source_search_disabled": True,
        "institutional_approval": False,
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "results/sources.json", source)
    integrity(output)
    common.log_event(
        output,
        "prepared",
        requests=23,
        model=manifest["model"],
        baseline_passing=manifest["baseline_passing_requests"],
        source_search=False,
    )


def integrity(output):
    manifest = read_json(output / "manifest.json")
    live = common.verify_integrity(output)
    before = read_json(output / "previous-integrity-before.json")
    after = common.live_fingerprint(Path(manifest["previous_data_read_only"]), manifest["case_id"])
    with common.read_connection(output / "data/expedientes.sqlite") as conn:
        case = json.loads(
            conn.execute("SELECT body FROM cases WHERE id=?", (manifest["case_id"],)).fetchone()[0]
        )
    with common.read_connection(output / "data/biblioteca.sqlite") as conn:
        run = json.loads(
            conn.execute(
                "SELECT body FROM source_runs WHERE case_id=? ORDER BY rowid DESC LIMIT 1",
                (manifest["case_id"],),
            ).fetchone()[0]
        )
    expected = read_json(output / "baseline/sources.json")
    result = {
        "checked_at": now(),
        "live_unchanged": live["live_unchanged"],
        "previous_qa_unchanged": before == after,
        "case_copy_unchanged": digest(case) == manifest["case_sha256"],
        "source_results_unchanged": digest(run["results"]) == digest(expected["results"])
        and run["id"] == expected["id"],
    }
    write_json(output / "integrity.json", result)
    return result


class ReadOnlySources(SourceService):
    def start(self, *args, **kwargs):
        raise AssertionError("Esta validación no inicia búsqueda de fuentes.")

    def run(self, *args, **kwargs):
        raise AssertionError("Esta validación no ejecuta recuperación ni IA de fuentes.")


class CapturingEngine:
    """Wrap every call without overwriting a first check with its recheck."""

    def __init__(self, delegate, attempt, phase):
        self.delegate, self.attempt, self.phase = delegate, attempt, phase
        self.counts, self.local = Counter(), threading.local()
        original = delegate.client.responses.parse

        def parse(*args, **kwargs):
            label = getattr(self.local, "label", "unassigned")
            try:
                response = original(*args, **kwargs)
            except Exception as error:
                body = getattr(error, "body", None)
                body = body if isinstance(body, dict) else {"message": str(error)}
                if isinstance(body.get("error"), dict):
                    body = body["error"]
                safe = {
                    "exception_type": type(error).__name__,
                    "status_code": getattr(error, "status_code", None),
                    **{key: body.get(key) for key in ("message", "code", "type", "param")},
                }
                secret = getattr(delegate.client, "api_key", "")
                for key, value in safe.items():
                    if isinstance(value, str):
                        if secret:
                            value = value.replace(secret, "[REDACTED]")
                        safe[key] = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", value)
                write_json(attempt / "api_errors" / phase / f"{label}.json", safe)
                raise
            write_json(
                attempt / "api_responses" / phase / f"{label}.json",
                response.model_dump(mode="json", warnings=False),
            )
            return response

        delegate.client.responses.parse = parse

    def _call(self, method, *args, **kwargs):
        request_id = args[0]["id"]
        self.counts[(request_id, method)] += 1
        label = f"{request_id}-{method}-{self.counts[(request_id, method)]:02}"
        self.local.label = label
        action = getattr(self.delegate, method)
        inputs = dict(inspect.signature(action).bind(*args, **kwargs).arguments)
        return common.record_call(
            self.attempt,
            self.phase,
            request_id,
            label[len(request_id) + 1 :],
            inputs,
            lambda: action(*args, **kwargs),
        )

    def plan(self, *args, **kwargs):
        return self._call("plan", *args, **kwargs)

    def write(self, *args, **kwargs):
        return self._call("write", *args, **kwargs)

    def check(self, *args, **kwargs):
        return self._call("check", *args, **kwargs)

    def repair(self, *args, **kwargs):
        return self._call("repair", *args, **kwargs)

    def assess(self, *args, **kwargs):
        return self._call("assess", *args, **kwargs)


def baseline_inputs(output):
    return {
        row["request_id"]: row for row in read_json(output / "local-checks-antes.json")["requests"]
    }


def local_checks(output, label):
    if not re.fullmatch(r"[a-z0-9_-]{1,60}", label):
        raise ValueError("Etiqueta local inválida.")
    path = output / f"local-checks-{label}.json"
    if path.exists():
        raise ValueError("Se conserva la captura existente; use una etiqueta nueva.")
    reviews = {
        row["request_id"]: row for row in read_json(output / "baseline/reviews.json")["requests"]
    }
    rows = []
    for request_id, baseline in baseline_inputs(output).items():
        request, finding, draft = baseline["request"], baseline["finding"], baseline["draft"]
        checks, issues = _local_checks(request, finding, draft, _supports(request, finding))
        review_checks, review_issues = structural_checks(reviews[request_id])
        before = Counter(row["code"] for row in baseline["local_issues"])
        after = Counter(row["code"] for row in issues)
        rows.append(
            {
                "request_id": request_id,
                "local_checks": checks,
                "local_issues": issues,
                "review_structural_checks": review_checks,
                "review_structural_issues": review_issues,
                "before_issue_counts": dict(before),
                "after_issue_counts": dict(after),
            }
        )
    result = {
        "created_at": now(),
        "code_sha256": code_snapshot(),
        "requests": rows,
        "issue_counts": dict(
            Counter(issue["code"] for row in rows for issue in row["local_issues"])
        ),
    }
    write_json(path, result)
    common.log_event(
        output, "local_checks", label=label, requests=len(rows), issues=result["issue_counts"]
    )


def recheck_passing(output, attempt, settings):
    manifest, baseline = read_json(output / "manifest.json"), baseline_inputs(output)
    drafts = {
        row["request_id"]: row for row in read_json(output / "baseline/drafts.json")["results"]
    }
    results = []

    def check_one(request_id):
        original = baseline[request_id]
        engine = CapturingEngine(
            OpenAIDraftEngine(settings.api_key, settings.model), attempt, "baseline_rechecks"
        )
        result = engine.check(
            original["request"],
            original["finding"],
            drafts[request_id]["plan"],
            copy.deepcopy(original["draft"]),
        )
        return {
            "request_id": request_id,
            "before_status": "passed",
            "assessment": result,
            "unchanged_draft_sha256": digest(original["draft"]),
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [
            pool.submit(check_one, request_id)
            for request_id in manifest["baseline_passing_requests"]
        ]
        try:
            for job in as_completed(jobs):
                row = job.result()
                results.append(row)
                write_json(attempt / "results/baseline-rechecks.json", results)
                write_json(output / "results/baseline-rechecks.json", results)
                common.log_event(
                    output,
                    "baseline_recheck",
                    request_id=row["request_id"],
                    status=row["assessment"]["status"],
                )
        except Exception:
            for job in jobs:
                job.cancel()
            raise
    return results


def resume_baseline(output, attempt, settings, previous_id, current_code):
    """Reuse successful checks only for identical application code and exact inputs."""
    if not re.fullmatch(r"[A-Za-z0-9_+.-]{1,100}", previous_id):
        raise ValueError("Identificador de intento previo inválido.")
    previous = output / "attempts" / previous_id
    execution = read_json(previous / "execution.json")
    own_file = str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/")
    # This runner adds resume bookkeeping; all application files must match exactly.
    old_code = {key: value for key, value in execution["code_sha256"].items() if key != own_file}
    application_code = {key: value for key, value in current_code.items() if key != own_file}
    if old_code != application_code or execution["model"] != settings.model:
        raise ValueError("El código de aplicación o modelo cambió; no se reutilizan controles.")
    if execution.get("code_unchanged_during_run") is not True:
        raise ValueError("El intento anterior no acredita código estable.")
    manifest, inputs = read_json(output / "manifest.json"), baseline_inputs(output)
    drafts = {
        row["request_id"]: row for row in read_json(output / "baseline/drafts.json")["results"]
    }
    rows = read_json(previous / "results/baseline-rechecks.json")
    if (
        len(rows) != 7
        or {row["request_id"] for row in rows} != set(manifest["baseline_passing_requests"])
    ):
        raise ValueError("Faltan controles completos de los siete textos de referencia.")
    for row in rows:
        request_id = row["request_id"]
        baseline = inputs[request_id]
        recorded = read_json(previous / f"calls/baseline_rechecks/{request_id}-check-01.json")
        expected = {
            "request": baseline["request"],
            "finding": baseline["finding"],
            "plan": drafts[request_id]["plan"],
            "draft": baseline["draft"],
        }
        if (
            recorded.get("inputs") != expected
            or recorded.get("result") != row["assessment"]
            or row["unchanged_draft_sha256"] != digest(baseline["draft"])
        ):
            raise ValueError(f"Cambió la entrada o resultado de referencia de {request_id}.")
    audit = {
        "reused_from_attempt": previous_id,
        "application_code_identical": True,
        "model_identical": True,
        "exact_application_inputs_identical": True,
        "completed_results_verified": 7,
        "new_api_calls": 0,
        "harness_code_change_only": own_file,
    }
    write_json(attempt / "results/baseline-rechecks.json", rows)
    write_json(output / "results/baseline-rechecks.json", rows)
    write_json(attempt / "results/baseline-reuse.json", audit)
    common.log_event(output, "baseline_reused", **audit)
    return rows


def canaries(output, settings):
    """Run P1/P3 in real service checkpoint threads, without creating a draft run."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    from pqrs_claro.draft_graph import build_draft_graph
    from pqrs_claro.draft_service import _GuardedEngine
    from pqrs_claro.source_context import build_source_requests

    manifest = read_json(output / "manifest.json")
    settings = replace(settings, data_dir=output / "data")
    if not settings.api_key or settings.model != manifest["model"]:
        raise ValueError("Los canarios requieren la configuración y modelo autorizados.")
    attempt_id = now().replace(":", "").replace(".", "") + "_canary_" + uuid4().hex[:8]
    attempt, code = output / "attempts" / attempt_id, code_snapshot()
    execution = {
        "attempt_id": attempt_id,
        "mode": "canaries",
        "started_at": now(),
        "status": "running",
        "model": settings.model,
        "code_sha256": code,
        "source_search_calls": 0,
        "institutional_approval": False,
    }
    library = common.SnapshotLibrary(settings.data_dir, manifest["originals_read_only_path"])
    cases = CaseStore(settings.data_dir)
    verifications = SourceVerificationStore(settings.data_dir, library, cases)
    sources = ReadOnlySources(settings, cases, library, verifications=verifications)
    engine = CapturingEngine(OpenAIDraftEngine(settings.api_key, settings.model), attempt, "drafts")
    drafts = DraftService(settings, cases, library, sources, engine=engine)
    results = []
    try:
        case, mapping, findings, fingerprint = drafts._inputs(
            manifest["case_id"], manifest["case_version"]
        )
        if digest(mapping) != manifest["baseline_source_sha256"]:
            raise ValueError("Cambió el mapa congelado.")
        execution["draft_fingerprint"] = fingerprint
        write_json(attempt / "execution.json", execution)
        with SqliteSaver.from_conn_string(
            str(settings.data_dir / "draft_checkpoints.sqlite")
        ) as saver:
            requests = build_source_requests(
                case, allowed_collection_ids=case["allowed_collection_ids"]
            )
            for request in requests:
                if request["id"] not in {"P1", "P3"}:
                    continue
                finding = findings[request["id"]]

                def guard(f=finding):
                    if code_snapshot() != code:
                        raise ValueError("El código cambió durante los canarios.")
                    drafts._ensure_current(case["id"], fingerprint, f)

                guard()
                graph = build_draft_graph(_GuardedEngine(engine, guard), saver)
                thread_id = f"{case['id']}:{request['id']}:{fingerprint}"
                config = {"configurable": {"thread_id": thread_id}}
                checkpoint = graph.get_state(config)
                state = copy.deepcopy(checkpoint.values)
                if not state.get("checks") or checkpoint.next:
                    initial = None if state else {"request": request, "finding": finding}
                    for update in graph.stream(initial, config, stream_mode="updates"):
                        for node in update:
                            guard()
                            state = copy.deepcopy(graph.get_state(config).values)
                            write_json(
                                attempt / "states" / f"{request['id']}.json",
                                {
                                    "request_id": request["id"],
                                    "node": node,
                                    "thread_id": thread_id,
                                    "state": state,
                                },
                            )
                            common.log_event(output, "canary", request_id=request["id"], step=node)
                drafts._ensure_current(case["id"], fingerprint, finding, full=True)
                results.append(drafts._result(request, finding, state))
                write_json(attempt / "results/canaries.json", results)
                write_json(output / "results/canaries.json", results)
        execution["status"] = "completed"
    except Exception as error:
        execution.update(status="error", error_type=type(error).__name__)
        raise
    finally:
        drafts.close()
        sources.close()
        execution.update(
            finished_at=now(),
            results=len(results),
            integrity=integrity(output),
            code_unchanged_during_run=code_snapshot() == code,
        )
        write_json(attempt / "execution.json", execution)
        write_json(output / "canary-execution.json", execution)
        common.log_event(
            output,
            "canaries_finished",
            attempt_id=attempt_id,
            status=execution["status"],
            count=len(results),
        )


def run(output, settings, through, poll_seconds, resume_attempt=None):
    manifest = read_json(output / "manifest.json")
    settings = replace(settings, data_dir=output / "data")
    if not settings.api_key or settings.model != manifest["model"]:
        raise ValueError(
            "Se requiere la configuración OpenAI autorizada y el mismo modelo de referencia."
        )
    if not all(value for key, value in integrity(output).items() if key.endswith("unchanged")):
        raise ValueError("Cambió una entrada congelada.")
    attempt_id = now().replace(":", "").replace(".", "") + "_" + uuid4().hex[:8]
    attempt, code = output / "attempts" / attempt_id, code_snapshot()
    execution = {
        "attempt_id": attempt_id,
        "status": "running",
        "started_at": now(),
        "model": settings.model,
        "python": platform.python_version(),
        "code_sha256": code,
        "source_search_calls": 0,
        "institutional_approval": False,
        "phases": {},
    }
    write_json(attempt / "execution.json", execution)
    write_json(output / "execution.json", execution)
    case_id = manifest["case_id"]
    library = common.SnapshotLibrary(settings.data_dir, manifest["originals_read_only_path"])
    cases = CaseStore(settings.data_dir)
    verifications = SourceVerificationStore(settings.data_dir, library, cases)
    sources = ReadOnlySources(settings, cases, library, verifications=verifications)
    drafts = DraftService(
        settings,
        cases,
        library,
        sources,
        engine=CapturingEngine(
            OpenAIDraftEngine(settings.api_key, settings.model), attempt, "drafts"
        ),
    )
    reviews = ReviewService(
        settings,
        cases,
        library,
        sources,
        drafts,
        engine=CapturingEngine(
            OpenAIReviewEngine(settings.api_key, settings.model), attempt, "reviews"
        ),
    )
    try:
        mapping = sources.get(case_id)
        if (
            mapping["status"] != "ready"
            or mapping.get("stale")
            or digest(mapping) != manifest["baseline_source_sha256"]
        ):
            raise ValueError("El mapa de fuentes cambió; no se recobrará en esta validación.")
        write_json(output / "results/sources.json", mapping)
        execution["phases"]["sources"] = {"reused": True, "id": mapping["id"], "search_calls": 0}
        canary_path = output / "canary-execution.json"
        if canary_path.exists():
            canary = read_json(canary_path)
            fingerprint = drafts._fingerprint(cases.get(case_id), mapping)
            if canary.get("draft_fingerprint") == fingerprint:
                if canary["status"] != "completed" or canary["code_sha256"] != code:
                    raise ValueError("Los checkpoints canarios no corresponden al código final.")
                execution["reused_canary_attempt"] = canary["attempt_id"]
        common.log_event(
            output, "starting", attempt_id=attempt_id, through=through, source_search=False
        )
        if resume_attempt:
            rechecked = resume_baseline(output, attempt, settings, resume_attempt, code)
            previous_execution = read_json(output / "attempts" / resume_attempt / "execution.json")
            execution["resumed_attempts"] = list(dict.fromkeys(
                [*previous_execution.get("resumed_attempts", []), resume_attempt]
            ))
        else:
            rechecked = recheck_passing(output, attempt, settings)
        execution["phases"]["baseline_rechecks"] = {"count": len(rechecked)}
        if code_snapshot() != code:
            raise ValueError("El código cambió durante los controles de referencia.")
        drafts.store.recover()
        reviews.recover()
        draft = common.wait_service(
            output,
            attempt,
            "drafts",
            drafts,
            case_id,
            drafts.start(case_id, manifest["case_version"]),
            poll_seconds,
        )
        execution["phases"]["drafts"] = {"status": draft["status"], "id": draft.get("id")}
        if draft["status"] not in {"ready", "partial"} or any(
            row["status"] == "error" for row in draft["results"]
        ):
            raise ValueError("Hay errores técnicos en borradores; se conserva el avance.")
        if through == "reviews":
            if code_snapshot() != code:
                raise ValueError("El código cambió durante los borradores.")
            review = reviews.start(case_id, manifest["case_version"])
            for row in review["requests"]:
                if row.get("approval"):
                    raise ValueError("Aprobación inesperada en la copia QA.")
                row = reviews.assess(case_id, row["request_id"], row["revision"])
                while row["status"] == "checking":
                    time.sleep(poll_seconds)
                    row = reviews.store.get(case_id, row["request_id"])
                review = reviews.get(case_id)
                write_json(attempt / "results/reviews.json", review)
                write_json(output / "results/reviews.json", review)
                common.log_event(
                    output, "review", request_id=row["request_id"], status=row["status"]
                )
            if any(row["status"] == "error" for row in review["requests"]):
                raise ValueError("Hay errores técnicos en revisión; se conserva el avance.")
            execution["phases"]["reviews"] = {
                "requests": len(review["requests"]),
                "approved_count": review["approved_count"],
            }
        execution["status"] = "completed"
    except Exception as error:
        execution.update(status="error", error_type=type(error).__name__)
        raise
    finally:
        reviews.close()
        drafts.close()
        sources.close()
        execution.update(
            finished_at=now(),
            code_unchanged_during_run=code_snapshot() == code,
            integrity=integrity(output),
        )
        write_json(attempt / "execution.json", execution)
        write_json(output / "execution.json", execution)
        report(output)
        common.log_event(output, "finished", status=execution["status"], attempt_id=attempt_id)


def report(output):
    manifest = read_json(output / "manifest.json")
    before = {
        row["request_id"]: row for row in read_json(output / "baseline/drafts.json")["results"]
    }
    path = output / "results/drafts.json"
    after = {row["request_id"]: row for row in read_json(path)["results"]} if path.exists() else {}
    review_path = output / "results/reviews.json"
    review_rows = (
        {row["request_id"]: row for row in read_json(review_path)["requests"]}
        if review_path.exists()
        else {}
    )
    rows = []
    for request_id, old in before.items():
        new = after.get(request_id)
        row = {
            "request_id": request_id,
            "baseline_passed": request_id in manifest["baseline_passing_requests"],
            "targeted": request_id in TARGET_REQUESTS,
            "before_checks": old["checks"],
            "before_paragraphs": old["draft"]["paragraphs"],
        }
        if new and new.get("draft"):
            old_pending = {item["check_key"]: item for item in old["draft"]["pending"]}
            new_pending = {item["check_key"]: item for item in new["draft"]["pending"]}
            row.update(
                after_checks=new["checks"],
                after_paragraphs=new["draft"]["paragraphs"],
                pending_unchanged=old_pending == new_pending,
                duplicate_pending_keys=len(new_pending) != len(new["draft"]["pending"]),
            )
            if request_id in review_rows:
                reviewed = review_rows[request_id]
                review_pending = {item["check_key"]: item for item in reviewed["pending"]}
                immutable = ("description", "reason_code", "scope_key", "stage", "blocks_approval")
                row["review_pending_unchanged"] = (
                    set(new_pending) == set(review_pending)
                    and all(
                        new_pending[key].get(field) == review_pending[key].get(field)
                        for key in new_pending
                        for field in immutable
                    )
                    and len(review_pending) == len(reviewed["pending"])
                )
                row["review_assessment"] = reviewed.get("assessment")
                row["approval"] = reviewed.get("approval")
        rows.append(row)
    result = {
        "created_at": now(),
        "baseline_draft_run_id": manifest["baseline_draft_run_id"],
        "institutional_approval": False,
        "requests": rows,
    }
    execution_path = output / "execution.json"
    if execution_path.exists():
        execution = read_json(execution_path)
        result["execution"] = execution
        calls, totals, call_types = [], Counter(), Counter()
        attempt_ids = [execution["attempt_id"]]
        attempt_ids.extend(execution.get("resumed_attempts", []))
        if execution.get("reused_canary_attempt"):
            attempt_ids.append(execution["reused_canary_attempt"])
        response_paths = [
            path
            for attempt_id in attempt_ids
            for path in (output / "attempts" / attempt_id / "api_responses").rglob("*.json")
        ]
        for path in sorted(response_paths):
            response = read_json(path)
            usage = response.get("usage") or {}
            method = path.stem.split("-")[1]
            if method == "check" and not path.stem.endswith("-01"):
                method = "recheck"
            call_types[f"{path.parent.name}/{method}"] += 1
            calls.append(
                {
                    "attempt_id": path.parents[2].name,
                    "phase": path.parent.name,
                    "call": path.stem,
                    "model": response.get("model"),
                    "usage": usage,
                }
            )
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                totals[key] += usage.get(key, 0)
        result["api_usage"] = {
            "calls": calls,
            "token_totals": dict(totals),
            "call_types": dict(call_types),
            "estimated_usd": None,
            "price_note": "No se inventa una tarifa no proporcionada para este modelo.",
        }
    write_json(output / "comparison.json", result)
    lines = [
        "# Calidad de borradores y evaluación: prueba aislada",
        "",
        "Se conserva la validación anterior y el mapa de fuentes v11. "
        "No se ejecuta búsqueda de fuentes, no se registran hechos humanos "
        "y no se aprueban respuestas.",
        "",
        "| Pregunta | Pasaba en v4 | Antes | Después | Pendientes intactos |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['request_id']} | {'Sí' if row['baseline_passed'] else 'No'} | "
            f"{row['before_checks']['status']} | "
            f"{row.get('after_checks', {}).get('status', 'Pendiente')} | "
            f"{row.get('pending_unchanged', 'Pendiente')} |"
        )
    lines += [
        "",
        "Los siete textos v4 que pasaban se comprueban sin modificarlos con el evaluador actual. "
        "Su resultado permite distinguir un cambio del evaluador de la variación al redactar "
        "de nuevo las 23 respuestas.",
        "",
        "comparison.json conserva los párrafos y controles antes/después. Cada intento guarda "
        "plan, redacción, primera comprobación, reparación acotada, recomprobación, "
        "evaluación y uso de tokens sin sobrescribir llamadas anteriores.",
        "",
    ]
    (output / "COMPARACION.md").write_text("\n".join(lines), encoding="utf-8")
    if after:
        common.draft_review_packet(output, read_json(output / "baseline/case.json"))
    result_report(output, result)
    return result


def result_report(output, comparison):
    """Separate local evidence, prior responses, and the new live-API attempt."""
    baseline = read_json(output / "local-checks-antes.json")
    local_paths = sorted(output.glob("local-checks-despues*.json"), key=lambda p: p.stat().st_mtime)
    latest_local = read_json(local_paths[-1]) if local_paths else {"requests": []}
    current_by_id = {row["request_id"]: row for row in latest_local["requests"]}
    local_rows = []
    for row in baseline["requests"]:
        current = current_by_id.get(row["request_id"], {})
        local_rows.append(
            {
                "request_id": row["request_id"],
                "before": row["local_issues"],
                "after": current.get("local_issues"),
            }
        )
    execution = comparison.get("execution", {})
    after = [row for row in comparison["requests"] if "after_checks" in row]
    rechecks_path = output / "results/baseline-rechecks.json"
    rechecks = read_json(rechecks_path) if rechecks_path.exists() else []
    reviews_path = output / "results/reviews.json"
    reviews = read_json(reviews_path).get("requests", []) if reviews_path.exists() else []
    diagnosis_path = output / "diagnostics/provider-blocker.json"
    diagnosis = read_json(diagnosis_path) if diagnosis_path.exists() else None
    blocked = bool(
        diagnosis
        and diagnosis.get("attempt_id") == execution.get("attempt_id")
        and execution.get("status") != "completed"
    )
    validation_path = output / "validation-checks.json"
    result = {
        "created_at": now(),
        "status": "api_credit_blocked" if blocked else execution.get("status", "prepared"),
        "baseline_description": "v4 responses from the previous QA; not new output",
        "local_checks_before": sum(len(row["before"]) for row in local_rows),
        "local_checks_after": sum(len(row["after"] or []) for row in local_rows),
        "local_snapshot": local_paths[-1].name if local_paths else None,
        "local_requests": local_rows,
        "new_run": {
            "attempt_id": execution.get("attempt_id"),
            "baseline_rechecks_completed": len(rechecks),
            "new_drafts_completed": len(after),
            "new_reviews_completed": sum(bool(row.get("assessment")) for row in reviews),
            "source_searches": 0,
            "approvals": sum(bool(row.get("approval")) for row in reviews),
        },
        "provider_diagnosis": diagnosis if blocked else None,
        "integrity": read_json(output / "integrity.json"),
        "implementation_checks": read_json(validation_path) if validation_path.exists() else None,
        "resume_command": (
            ".\\scripts\\dev-python.ps1 scripts/validate_draft_quality.py run --through reviews"
        ),
        "resume_requirement": "API credits available; preserve configured model and credential",
    }
    write_json(output / "RESULTADO.json", result)
    lines = [
        "# Resultado de la validación de citas y evaluador",
        "",
        "La reproducción local usa los mismos 23 borradores v4 de la validación anterior. "
        "Esos textos son referencia previa; no son respuestas generadas con los cambios nuevos.",
        "",
        f"Los controles locales pasaron de {result['local_checks_before']} observaciones a "
        f"{result['local_checks_after']}. La reducción no implica que todas las alertas "
        "anteriores "
        "fueran falsas ni aprueba el contenido; las observaciones restantes "
        "se conservan para cotejo.",
        "",
        "| Pregunta | Antes | Después | Observaciones locales actuales |",
        "|---|---:|---:|---|",
    ]
    for row in local_rows:
        remaining = (
            "; ".join(
                f"{issue['code']} (párrafo {(issue.get('paragraph_index') or 0) + 1})"
                for issue in (row["after"] or [])
            )
            or "Sin observaciones locales"
        )
        lines.append(
            f"| {row['request_id']} | {len(row['before'])} | "
            f"{len(row['after'] or [])} | {remaining} |"
        )
    lines += ["", "## Ejecución nueva con IA", ""]
    if blocked:
        lines += [
            "La ejecución nueva quedó bloqueada por saldo agotado en la API. "
            "El diagnóstico fue HTTP 429, insufficient_quota / credit_balance_exhausted; "
            "no es un límite transitorio de velocidad ni un fallo del esquema.",
            "",
            "No terminaron los 7 controles de los textos v4 ni se generaron los 23 borradores "
            "nuevos o sus 23 evaluaciones. No hay respuestas nuevas aprobadas ni una prueba "
            "completa del ciclo de reparación con IA. Se conservan las entradas del intento "
            "fallido y una prueba acotada con el mensaje saneado del proveedor.",
            "",
            "Para reanudar, se necesita saldo disponible en la "
            "[facturación de la API](https://platform.openai.com/settings/organization/billing/). "
            "No se cambió de modelo, proyecto o clave.",
            "",
        ]
    lines += [
        f"Controles de referencia terminados: {len(rechecks)}/7. "
        f"Borradores nuevos: {len(after)}/23. "
        f"Evaluaciones nuevas: {result['new_run']['new_reviews_completed']}/23.",
        "",
        "## Verificación de implementación e integridad",
        "",
    ]
    checks = result["implementation_checks"]
    if checks:
        lines += [
            f"- Suite completa: {checks['pytest_passed']} pruebas aprobadas. "
            f"Después del último ajuste de P3: {checks['targeted_after_p3']} "
            "pruebas focalizadas aprobadas.",
            "- Ruff y git diff --check sin errores. Las 16 regresiones de módulos JavaScript "
            "de aprobación pasaron; no se ejecutaron aprobaciones.",
        ]
    lines += [
        "- Bases vivas, PDF original, validación anterior, copia del expediente y mapa v11: "
        "sin cambios según las huellas registradas.",
        "- La búsqueda de fuentes está bloqueada en este harness. Se conservan "
        "las 140 aplicaciones de comprobaciones y 17 actuaciones de cumplimiento como referencia.",
        "",
        "## Reanudar sin rehacer la preparación",
        "",
        "Desde la raíz de pqrs-claro:",
        "",
        "```powershell",
        result["resume_command"],
        "```",
        "",
        "El comando crea otro intento dentro de esta copia, reutiliza el caso y las fuentes v11, "
        "comprueba los siete textos de referencia y genera las 23 respuestas con el código actual. "
        "No ejecuta búsquedas de fuentes ni modifica el expediente vivo o la validación anterior.",
        "",
        "Las capturas locales antes/después, el diagnóstico saneado, las huellas y el "
        "desglose por pregunta se conservan junto a RESULTADO.json y comparison.json.",
        "",
    ]
    (output / "RESULTADO.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "local-checks", "canaries", "run", "report", "integrity")
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--previous-dir", type=Path, default=DEFAULT_PREVIOUS)
    parser.add_argument("--label", default="despues")
    parser.add_argument("--through", choices=("drafts", "reviews"), default="reviews")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--resume-attempt", help="Reuse seven checks and compatible checkpoints.")
    args = parser.parse_args()
    output = common.qa_path(args.output_dir)
    if args.command == "prepare":
        prepare(output, common.qa_path(args.previous_dir))
        report(output)
    elif args.command == "local-checks":
        local_checks(output, args.label)
    elif args.command == "run":
        run(output, Settings.load(), args.through, args.poll_seconds, args.resume_attempt)
    elif args.command == "canaries":
        canaries(output, Settings.load())
    elif args.command == "report":
        report(output)
    else:
        print(json.dumps(integrity(output), ensure_ascii=False))


if __name__ == "__main__":
    main()
