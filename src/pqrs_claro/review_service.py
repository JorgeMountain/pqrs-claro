"""Revisión humana por solicitud, con evaluación y aprobación de entradas exactas."""

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .document_decisions import canonical_document_decision
from .evidence_contract import normalize_pending, pending_identity
from .models import DomainError
from .performance_metrics import track_case
from .response_reading import reading_state
from .review_store import ReviewStore
from .service import user_error
from .source_assessment import _allowed_roles
from .source_context import build_source_requests
from .source_documents import document_matches, requested_document
from .source_library import digest
from .storage import Conflict, now

REVIEW_VERSION = 7


def pending_id(item):
    return pending_identity(item)


def blocks_approval(item):
    return item.get("blocks_approval", True) is not False


def _pending_basis(item):
    return digest(
        {
            **{
                key: item.get(key)
                for key in (
                    "kind",
                    "stage",
                    "scope_key",
                    "source_versions",
                    "linked_source_ids",
                    "linked_chunk_ids",
                    "blocks_approval",
                )
            },
            "description": " ".join(item["description"].split()).casefold(),
        }
    )


def input_hash(row):
    return digest(
        {
            key: row.get(key)
            for key in (
                "case_id",
                "request_id",
                "base_fingerprint",
                "sufficiency",
                "paragraphs",
                "facts",
                "pending",
                "available_supports",
                "request_snapshot",
                "source_checks",
                "evidence_states",
                "verifications",
                "request_intent",
            )
        }
    )


def invalidate(row):
    row.update(
        status="stale" if row.get("stale") else "editing",
        assessment=None,
        approval=None,
        error=None,
        check_thread_id=None,
    )


class ReviewService:
    def __init__(self, settings, cases, library, sources_service, drafts_service, engine=None):
        self.settings, self.cases, self.library = settings, cases, library
        self.sources_service, self.drafts_service = sources_service, drafts_service
        self.engine = engine
        self.store = ReviewStore(settings.data_dir)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reviews")
        self.active = set()
        self._approval_inputs_cache = {}

    def _base(self, case_id):
        case, sources, fingerprint, current = self.drafts_service._current(case_id)
        return (
            case,
            sources,
            digest(
                {
                    "inputs": fingerprint,
                    "model": self.settings.model,
                    "review_version": REVIEW_VERSION,
                }
            ),
            current,
        )

    def _current(self, row, base=None):
        case, _, fingerprint, current = base or self._base(row["case_id"])
        if (
            row.get("stale")
            or not current
            or row["base_fingerprint"] != fingerprint
            or row["request_id"]
            not in {
                request["id"] for request in (case.get("identification") or {}).get("requests", [])
            }
        ):
            return False
        try:
            self.cases.original(row["case_id"])
            for source_id in {s["source_id"] for s in row["available_supports"]}:
                self.library.original(source_id, row["case_id"])
        except (ValueError, KeyError):
            return False
        return True

    def _project(self, row, base=None):
        if not self._current(row, base) and not row.get("stale"):
            row.update(
                stale=True,
                status="stale",
                assessment=None,
                approval=None,
                error="Actualiza las fuentes y sincroniza la revisión. Tu texto se conserva.",
                check_thread_id=None,
            )
            row = self.store.save(row, expected=row["revision"], event="inputs_changed")
        elif row.get("assessment") and row["assessment"].get("input_hash") != input_hash(row):
            invalidate(row)
            row = self.store.save(row, expected=row["revision"], event="revision_changed")
        return row

    def get(self, case_id):
        with self.lock:
            base = self._base(case_id)
            case = base[0]
            ids = [r["id"] for r in (case.get("identification") or {}).get("requests", [])]
            rows = {row["request_id"]: row for row in self.store.list(case_id)}
            requests = [self._project(rows[key], base) for key in ids if key in rows]
            stale = any(row["stale"] for row in requests)
            count = sum(row["status"] == "approved" for row in requests)
            status = (
                "idle"
                if not requests
                else "stale"
                if stale
                else "checking"
                if any(row["status"] == "checking" for row in requests)
                else "approved"
                if count == len(ids) and len(requests) == len(ids)
                else "ready"
                if len(requests) == len(ids)
                and all(row["status"] in {"ready", "approved"} for row in requests)
                else "editing"
            )
            return dict(
                case_id=case_id,
                status=status,
                stale=stale,
                requests=requests,
                approved_count=count,
                total_count=len(ids),
                reading_confirmation=reading_state(case, requests, self.store.reading(case_id)),
                error=None,
            )

    def confirm_reading(self, case_id, confirmation):
        body = confirmation.model_dump()
        with self.lock, self.library.lock:
            self.cases.assert_open(case_id)
            review = self.get(case_id)
            state = review["reading_confirmation"]
            if not state["eligible"]:
                raise Conflict("Espera a que estén guardadas todas las respuestas actuales.")
            if body["content_hash"] != state["content_hash"]:
                raise Conflict("Las respuestas cambiaron. Recarga y revisa la versión actual.")
            self.store.save_reading({
                "case_id": case_id, "content_hash": state["content_hash"],
                "response_count": state["response_count"],
                "reviewed_by": body["reviewed_by"], "reviewed_at": now(),
            }, {row["request_id"]: row["revision"] for row in review["requests"]})
            return self.get(case_id)

    def _inputs(self, case_id, version):
        case, source_run, findings, _ = self.drafts_service._inputs(case_id, version)
        # El mapa ya valida el catálogo completo. La revisión sólo materializa y
        # vuelve a cotejar los originales de sus soportes/candidatos concretos.
        selected = {source["source_id"] for finding in findings.values()
                    for source in [*finding.get("supports", []),
                                   *finding.get("candidate_documents", [])]}
        _, chunks = self.library.snapshot(case_id, source_ids=selected)
        return (
            case,
            source_run,
            findings,
            {c["chunk_id"]: c for c in chunks},
            self._base(case_id)[2],
        )

    @staticmethod
    def _supports(request, finding, chunks):
        available = {
            s["chunk_id"]: {**s, "origin_selection": "automatic"}
            for s in finding.get("supports", [])
        }
        kind = requested_document(request)
        for document in finding.get("candidate_documents", []):
            for fragment in document["chunks"]:
                chunk = chunks[fragment["chunk_id"]]
                roles = _allowed_roles(chunk["category"], kind)
                role = (
                    "document"
                    if "document" in roles
                    and kind
                    and document_matches(
                        request,
                        chunk,
                        kind,
                    )
                    else roles[0]
                    if roles
                    else None
                )
                if not role:
                    raise Conflict("Un candidato tiene una categoría no permitida.")
                available.setdefault(
                    chunk["chunk_id"], {**chunk, "role": role, "origin_selection": "candidate"}
                )
        if len(available) > 32:
            raise Conflict("El mapa supera 32 fragmentos para una solicitud. Ajusta sus fuentes.")
        return list(available.values())

    @staticmethod
    def _pending(old, finding, draft=None, request=None):
        request = request or {"id": finding.get("request_id", "unknown")}
        previous = {pending_id(item): item for item in old}
        source_items = normalize_pending(request, finding, [])
        source_ids = {pending_id(item) for item in source_items}
        items = normalize_pending(request, finding, (draft or {}).get("pending", []))
        entries = {}
        for item in items:
            identifier = pending_id(item)
            prior = previous.get(identifier)
            # Ni un nombre de check ni una resolución antigua bastan si cambió
            # su hecho, alcance o versión. El historial conserva el cierre previo.
            resolution = (
                deepcopy(prior.get("resolution"))
                if prior and _pending_basis(prior) == _pending_basis(item)
                else None
            )
            origins = ["source"] if identifier in source_ids else ["draft"]
            if identifier in source_ids and any(
                pending_id(candidate) == identifier
                for candidate in (draft or {}).get("pending", [])
            ):
                origins.append("draft")
            entries[identifier] = {
                **deepcopy(item),
                "id": identifier,
                "resolution": resolution,
                "origins": origins,
            }
        if len(entries) > 300:
            raise Conflict(
                "Hay más de 300 pendientes en esta solicitud. Ajusta el mapa de fuentes."
            )
        return list(entries.values())

    def start(self, case_id, version, *, before_draft=False):
        with self.lock, self.library.lock:
            self.cases.assert_open(case_id)
            if any(key[0] == case_id for key in self.active):
                raise Conflict("Espera a que termine la comprobación antes de sincronizar fuentes.")
            case, _, findings, chunks, fingerprint = self._inputs(case_id, version)
            previous = {row["request_id"]: row for row in self.store.list(case_id)}
            draft_run = self.drafts_service.get(case_id)
            draft_current = draft_run["status"] in {"ready", "partial"} and not draft_run["stale"]
            results = {r["request_id"]: r for r in draft_run.get("results", [])}
            if (
                not before_draft
                and not previous
                and (
                    not draft_current
                    or len(results) != len(findings)
                    or any(r["status"] == "error" for r in results.values())
                )
            ):
                raise Conflict("Prepara primero los borradores actuales de todas las solicitudes.")
            for request in build_source_requests(
                case, allowed_collection_ids=case["allowed_collection_ids"]
            ):
                if request["id"] not in findings:
                    continue
                finding, old = findings[request["id"]], previous.get(request["id"])
                draft = (results.get(request["id"], {}).get("draft") or {}) if draft_current else {}
                if results.get(request["id"], {}).get("status") == "error":
                    draft = {}
                expected_review = draft_run.get("review_snapshots", {}).get(request["id"])
                if (
                    old
                    and not old["paragraphs"]
                    and expected_review
                    and (self.drafts_service._review_input(old) != expected_review)
                ):
                    draft = {}
                supports = self._supports(request, finding, chunks)
                pending = self._pending((old or {}).get("pending", []), finding, draft, request)
                adopting = bool(old and not old["paragraphs"] and draft.get("paragraphs"))
                if (
                    old
                    and old["base_fingerprint"] == fingerprint
                    and not old["stale"]
                    and not adopting
                ):
                    continue
                if old:
                    row = deepcopy(old)
                    invalidate(row)
                    row.update(
                        base_fingerprint=fingerprint,
                        available_supports=supports,
                        pending=pending,
                        stale=False,
                        status="editing",
                        request_snapshot=request,
                        label=request["label"],
                        title=request["title"],
                        description=request["description"],
                        source_checks=deepcopy(finding.get("checks", [])),
                        evidence_states=deepcopy(finding.get("evidence_states", [])),
                        verifications=deepcopy(finding.get("verifications", [])),
                        request_intent=deepcopy(finding.get("request_intent")),
                        sufficiency=deepcopy(finding.get("sufficiency", {})),
                    )
                else:
                    row = dict(
                        case_id=case_id,
                        request_id=request["id"],
                        label=request["label"],
                        title=request["title"],
                        description=request["description"],
                        revision=0,
                        status="editing",
                        stale=False,
                        base_fingerprint=fingerprint,
                        draft_run_id=draft_run.get("id") if draft_current else None,
                        request_snapshot=request,
                        paragraphs=[
                            {**p, "cited_fact_ids": []} for p in draft.get("paragraphs", [])
                        ],
                        available_supports=supports,
                        facts=[],
                        pending=pending,
                        assessment=None,
                        approval=None,
                        error=None,
                        updated_at=now(),
                        edited_by=None,
                        check_thread_id=None,
                        pre_draft=not bool(draft.get("paragraphs")),
                        source_checks=deepcopy(finding.get("checks", [])),
                        evidence_states=deepcopy(finding.get("evidence_states", [])),
                        verifications=deepcopy(finding.get("verifications", [])),
                        request_intent=deepcopy(finding.get("request_intent")),
                        sufficiency=deepcopy(finding.get("sufficiency", {})),
                    )
                if adopting:
                    row.update(
                        paragraphs=[{**p, "cited_fact_ids": []} for p in draft["paragraphs"]],
                        draft_run_id=draft_run["id"],
                        pre_draft=False,
                    )
                self.store.save(
                    row,
                    expected=(old or {}).get("revision", 0),
                    event="synchronized" if old else "started",
                )
            return self.get(case_id)

    def _row(self, case_id, request_id, revision=None, *, fresh=True):
        case = self.cases.get(case_id)
        if request_id not in {
            r["id"] for r in (case.get("identification") or {}).get("requests", [])
        }:
            raise KeyError("La solicitud ya no forma parte de la identificación vigente.")
        row = self.store.get(case_id, request_id)
        if not row:
            raise KeyError("Inicia primero la revisión de esta solicitud.")
        row = self._project(row)
        if revision is not None and row["revision"] != revision:
            raise Conflict("La revisión cambió. Recarga antes de continuar.")
        if fresh and row["stale"]:
            raise Conflict("Actualiza las fuentes y sincroniza la revisión antes de continuar.")
        return row

    @staticmethod
    def _check_references(row, paragraphs, resolutions):
        chunks = {s["chunk_id"] for s in row["available_supports"]}
        facts = {fact["id"] for fact in row["facts"]}
        # Referencias retiradas ya presentes pueden conservarse al guardar; la evaluación
        # las señalará y no se elimina texto humano para esconder el problema.
        old_chunks = {identifier for p in row["paragraphs"] for identifier in p["cited_chunk_ids"]}
        old_facts = {identifier for p in row["paragraphs"] for identifier in p["cited_fact_ids"]}
        for paragraph in paragraphs:
            if (
                not set(paragraph["cited_chunk_ids"]) <= chunks | old_chunks
                or not set(paragraph["cited_fact_ids"]) <= facts | old_facts
            ):
                raise ValueError("Selecciona referencias disponibles en esta solicitud.")
        for resolution in resolutions:
            if resolution["action"] == "open":
                continue
            if (
                not set(resolution["cited_chunk_ids"]) <= chunks
                or not set(resolution["cited_fact_ids"]) <= facts
            ):
                raise ValueError("La resolución contiene referencias que ya no están disponibles.")

    def edit(self, case_id, request_id, edit, *, prepare_only=False):
        body = edit.model_dump(mode="json") if hasattr(edit, "model_dump") else edit
        body = deepcopy(body)

        def canonical_paragraphs(paragraphs):
            # La ausencia del campo ya significaba respuesta. Guardar esa misma
            # opción no debe retirar una aprobación histórica ni cambiar texto.
            result = deepcopy(paragraphs)
            for paragraph in result:
                if paragraph.get("office_section") == "response":
                    paragraph.pop("office_section")
            return result

        body["paragraphs"] = canonical_paragraphs(body["paragraphs"])
        with self.lock:
            self.cases.assert_open(case_id)
            row = self._row(case_id, request_id, body["revision"], fresh=False)
            if row["stale"] and any(
                item["action"] != "open" for item in body["pending_resolutions"]
            ):
                raise Conflict(
                    "Las fuentes cambiaron. Actualiza la preparación antes de confirmar "
                    "o descartar un pendiente. El texto puede seguir editándose."
                )
            self._check_references(row, body["paragraphs"], body["pending_resolutions"])
            pending = deepcopy(row["pending"])
            by_id = {item["id"]: item for item in pending}
            seen = set()
            for resolution in body["pending_resolutions"]:
                identifier = resolution["pending_id"]
                if identifier not in by_id or identifier in seen:
                    raise ValueError("El pendiente no existe o está repetido.")
                seen.add(identifier)
                item = by_id[identifier]
                if resolution["action"] == "open":
                    item["resolution"] = None
                    continue
                if item.get("state") == "analysis_error":
                    raise ValueError(
                        "Un error de análisis debe corregirse al actualizar las fuentes; "
                        "no se resuelve con una confirmación."
                    )
                if resolution.get("document_decision"):
                    resolution = canonical_document_decision(row, item, resolution)
                if row.get("pre_draft") and resolution["action"] == "resolved":
                    selected = [
                        s
                        for s in row["available_supports"]
                        if s["chunk_id"] in resolution["cited_chunk_ids"]
                    ]
                    if not selected or resolution["cited_fact_ids"]:
                        raise ValueError(
                            "Antes de redactar, confirma con un pasaje documental "
                            "o agrega la evidencia al expediente."
                        )
                    if item["kind"] == "document" and not any(
                        s.get("role") == "document" for s in selected
                    ):
                        raise ValueError(
                            "Localiza el documento solicitado; "
                            "una norma o una mención no sustituye su archivo."
                        )
                if (
                    resolution["action"] == "resolved"
                    and item["kind"] == "document"
                    and not resolution["cited_chunk_ids"]
                ):
                    raise ValueError(
                        "Un documento pendiente necesita una fuente documental citada."
                    )
                value = {
                    k: resolution[k]
                    for k in ("action", "note", "cited_chunk_ids", "cited_fact_ids")
                }
                if resolution.get("document_decision"):
                    value.update(
                        {
                            k: resolution[k]
                            for k in ("document_decision", "document_source_id", "document_version")
                        }
                    )
                old = item["resolution"]
                if old and all(old.get(key) == value[key] for key in value):
                    continue
                item["resolution"] = {**value, "by": body["edited_by"], "at": now()}
            if (
                canonical_paragraphs(row["paragraphs"]) == body["paragraphs"]
                and row["pending"] == pending
            ):
                return row
            row.update(paragraphs=body["paragraphs"], pending=pending, edited_by=body["edited_by"])
            invalidate(row)
            if prepare_only:
                return row
            return self.store.save(
                row, expected=body["revision"], event="edited", actor=body["edited_by"]
            )

    def add_fact(self, case_id, request_id, fact):
        body = fact.model_dump(mode="json") if hasattr(fact, "model_dump") else fact
        with self.lock:
            self.cases.assert_open(case_id)
            row = self._row(case_id, request_id, body["revision"], fresh=False)
            if len(row["facts"]) >= 30:
                raise ValueError("Esta solicitud admite hasta 30 declaraciones activas.")
            value = {key: body[key] for key in ("text", "author", "basis", "observed_at")}
            value.update(
                id="F" + uuid4().hex, recorded_at=now(), case_id=case_id, request_id=request_id
            )
            value["sha256"] = digest(value)
            row["facts"].append(value)
            row["edited_by"] = value["author"]
            invalidate(row)
            return self.store.save(
                row, expected=body["revision"], event="fact_added", actor=value["author"]
            )

    def remove_fact(self, case_id, request_id, fact_id, revision, edited_by):
        with self.lock:
            self.cases.assert_open(case_id)
            row = self._row(case_id, request_id, revision, fresh=False)
            if fact_id not in {fact["id"] for fact in row["facts"]}:
                raise KeyError("No existe la declaración activa.")
            row["facts"] = [fact for fact in row["facts"] if fact["id"] != fact_id]
            row["edited_by"] = edited_by
            invalidate(row)
            return self.store.save(row, expected=revision, event="fact_removed", actor=edited_by)

    def assess(self, case_id, request_id, revision):
        with self.lock:
            self.cases.assert_open(case_id)
            row = self._row(case_id, request_id, revision)
            key = (case_id, request_id)
            if key in self.active:
                raise Conflict("Esta solicitud ya se está comprobando.")
            if not self.settings.api_key and self.engine is None:
                raise ValueError("Falta configurar OpenAI para comprobar la revisión.")
            row.update(
                status="checking",
                assessment=None,
                approval=None,
                error=None,
                check_thread_id=f"review:{case_id}:{request_id}:{uuid4().hex}",
            )
            row = self.store.save(row, expected=revision, event="assessment_started")
            self.active.add(key)
            self.pool.submit(self.run, deepcopy(row))
            return row

    def _engine(self):
        from .review_engine import OpenAIReviewEngine

        return self.engine or OpenAIReviewEngine(self.settings.api_key, self.settings.model)

    @track_case("review", "original")
    def run(self, original):
        from .review_graph import build_review_graph

        key = (original["case_id"], original["request_id"])
        try:
            if not self._current(original):
                raise Conflict("Las fuentes cambiaron durante la comprobación.")
            with SqliteSaver.from_conn_string(
                str(self.settings.data_dir / "review_checkpoints.sqlite")
            ) as saver:
                graph = build_review_graph(self._engine(), saver)
                state = graph.invoke(
                    {
                        "request": original["request_snapshot"],
                        "review": original,
                        "input_hash": input_hash(original),
                    },
                    {"configurable": {"thread_id": original["check_thread_id"]}},
                )
            with self.lock:
                row = self.store.get(*key)
                if (
                    row["revision"] != original["revision"]
                    or row["check_thread_id"] != original["check_thread_id"]
                ):
                    return
                if not self._current(row):
                    self._project(row)
                    return
                assessment = {
                    **state["assessment"],
                    "input_hash": input_hash(row),
                    "assessed_at": now(),
                    "model": self.settings.model,
                }
                pending = any(
                    item["resolution"] is None
                    and blocks_approval(item)
                    and item.get("stage", "evidence") == "evidence"
                    for item in row["pending"]
                )
                row.update(
                    assessment=assessment,
                    error=None,
                    status="needs_evidence"
                    if pending
                    else "ready"
                    if assessment["status"] == "passed"
                    else "needs_changes",
                )
                self.store.save(row, expected=original["revision"], event="assessed")
        except Exception as exc:
            with self.lock:
                row = self.store.get(*key)
                if row and row["revision"] == original["revision"]:
                    if not self._current(row):
                        self._project(row)
                    else:
                        error = user_error(exc if isinstance(exc, DomainError) else RuntimeError())
                        row.update(status="error", error=error, assessment=None, approval=None)
                        self.store.save(row, expected=row["revision"], event="assessment_failed")
        finally:
            with self.lock:
                self.active.discard(key)

    def _validate_approval_inputs(self, case_id):
        """Reuse the common map check, only while its committed inputs match.

        Called under review/library locks. Keep hashing selected originals on
        every approval: filesystem changes do not advance the catalog revision.
        No response assessment, graph pause or human decision is cached here.
        """
        key = self.drafts_service._validation_key(case_id)
        cached = self._approval_inputs_cache.get(case_id)
        try:
            if cached and cached[0] == key:
                self.cases.original(case_id)
                for source_id in cached[1]:
                    self.library.original(source_id, case_id)
                if self.drafts_service._validation_key(case_id) == key:
                    return
                raise Conflict("Las fuentes cambiaron durante la aprobación. Recarga el oficio.")
            if getattr(self, "initial_review", None):
                self.initial_review.assert_allowed(case_id)
            case = self.cases.get(case_id)
            # _inputs already reconciles every selected passage. Approval does
            # not need the second materialization performed by review._inputs.
            _, run, _, _ = self.drafts_service._inputs(case_id, case["version"])
            selected = frozenset(source["source_id"] for finding in run.get("results", [])
                                 for source in [*finding.get("supports", []),
                                                *finding.get("candidate_documents", [])])
            if self.drafts_service._validation_key(case_id) != key:
                raise Conflict("Las fuentes cambiaron durante la aprobación. Recarga el oficio.")
            if len(self._approval_inputs_cache) >= 8 and case_id not in self._approval_inputs_cache:
                self._approval_inputs_cache.pop(next(iter(self._approval_inputs_cache)))
            self._approval_inputs_cache[case_id] = key, selected
        except Exception:
            self._approval_inputs_cache.pop(case_id, None)
            raise

    def approve(self, case_id, request_id, approval):
        from .review_graph import build_review_graph

        body = approval.model_dump(mode="json") if hasattr(approval, "model_dump") else approval
        with self.lock, self.library.lock:
            self.cases.assert_open(case_id)
            self._validate_approval_inputs(case_id)
            row = self._row(case_id, request_id, body["revision"])
            assessment, fingerprint = row["assessment"], input_hash(row)
            if (
                row["status"] != "ready"
                or not assessment
                or assessment["status"] != "passed"
                or body["assessment_hash"] != fingerprint
                or assessment["input_hash"] != fingerprint
                or not row["paragraphs"]
                or any(
                    item["resolution"] is None and blocks_approval(item) for item in row["pending"]
                )
            ):
                raise Conflict(
                    "Comprueba y resuelve los pendientes de esta versión antes de aprobar."
                )
            from .review_engine import structural_checks, validate_review_input

            _, issues = structural_checks(validate_review_input(row["request_snapshot"], row))
            if issues:
                raise Conflict("Corrige las citas y resoluciones de esta versión antes de aprobar.")
            case = self.cases.get(case_id)
            with SqliteSaver.from_conn_string(
                str(self.settings.data_dir / "review_checkpoints.sqlite")
            ) as saver:
                graph = build_review_graph(self._engine(), saver)
                config = {"configurable": {"thread_id": row["check_thread_id"]}}
                state = graph.get_state(config)
                if (
                    state.values.get("evaluated_input_hash") != fingerprint
                    or input_hash(state.values.get("review", {})) != fingerprint
                    or state.values.get("assessment")
                    != {key: assessment[key] for key in ("status", "issues", "local_checks")}
                ):
                    raise Conflict(
                        "La pausa de aprobación no corresponde a esta evaluación. "
                        "Comprueba de nuevo."
                    )
                decision = {key: body[key] for key in ("approved_by", "note", "confirmed")}
                resume = {**decision, "input_hash": fingerprint}
                if state.next == ("esperar_aprobacion",):
                    state = graph.invoke(Command(resume=resume), config)
                elif state.values.get("approval_decision") == resume:
                    # Un apagado puede ocurrir entre confirmar el grafo y guardar la
                    # proyección SQLite. La misma decisión explícita recupera ese corte.
                    if state.next == ("registrar_aprobacion",):
                        state = graph.invoke(None, config)
                    elif not state.next and state.values.get("approval"):
                        state = state.values
                    else:
                        raise Conflict("La pausa cambió. Vuelve a comprobar esta revisión.")
                else:
                    raise Conflict(
                        "La aprobación interrumpida tenía otra decisión. "
                        "Vuelve a comprobar antes de aprobar con datos diferentes."
                    )
            approved = state.get("approval")
            if not approved or approved["input_hash"] != fingerprint:
                raise Conflict("El grafo no confirmó la aprobación de esta versión.")
            if not self._current(row):
                self._project(row)
                raise Conflict("Las fuentes cambiaron antes de registrar la aprobación.")
            snapshot = dict(
                id=approved["id"],
                case_id=case_id,
                request_id=request_id,
                case_version=case["version"],
                case_original_sha256=case["sha256"],
                identification=deepcopy(case["identification"]),
                review=deepcopy(row),
                approval=deepcopy(approved),
            )
            snapshot["snapshot_hash"] = digest(snapshot)
            row.update(
                status="approved",
                approval={**approved, "snapshot_hash": snapshot["snapshot_hash"]},
                edited_by=body["approved_by"],
                error=None,
            )
            return self.store.save(
                row,
                expected=body["revision"],
                event="approved",
                actor=body["approved_by"],
                snapshot=snapshot,
            )

    def history(self, case_id, request_id):
        self.cases.get(case_id)
        if not self.store.get(case_id, request_id):
            raise KeyError("No existe historial de esta solicitud.")
        return {"revisions": self.store.history(case_id, request_id), "limit": 100}

    def approved(self, case_id):
        if getattr(self, "initial_review", None):
            # Reading the approved snapshot (including downloads) remains available
            # after closure. Editing and generation keep their assert_open guard.
            self.initial_review.assert_allowed(case_id, read_only=True)
        with self.lock:
            value = self.get(case_id)
            if value["status"] != "approved" or not value["requests"]:
                raise Conflict(
                    "Todas las respuestas vigentes deben estar aprobadas antes de continuar."
                )
            snapshots = [self.store.approval(row["approval"]["id"]) for row in value["requests"]]
            for row, snapshot in zip(value["requests"], snapshots, strict=True):
                if snapshot["snapshot_hash"] != digest(
                    {key: val for key, val in snapshot.items() if key != "snapshot_hash"}
                ) or row["approval"]["input_hash"] != input_hash(row):
                    raise Conflict("La versión aprobada no corresponde a la revisión vigente.")
            result = dict(
                case_id=case_id,
                status="approved",
                requests=snapshots,
                approved_count=len(snapshots),
                total_count=len(snapshots),
            )
            return {**result, "snapshot_hash": digest(result)}

    def recover(self):
        self.store.recover()

    def close(self):
        self.pool.shutdown(wait=True)
