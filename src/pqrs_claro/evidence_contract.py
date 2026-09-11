"""Comprobaciones trazables y estados simultáneos, independientes de la aprobación.

Los identificadores se calculan localmente. Una propuesta del modelo nunca puede
cerrar una comprobación ni declarar agotada una búsqueda del catálogo.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy

from .source_documents import named_document_candidates, numbered_document_references
from .verification_policy import application_matches_check

STATE_LABELS = {
    "support_found": "Respaldo encontrado",
    "confirmation_pending": "Confirmación pendiente",
    "document_missing": "Documento faltante",
    "analysis_error": "Error de análisis",
}
DOCUMENT_CHECKS = {"provenance", "issued_version", "validity"}


def _plain(value):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", str(value).lower())
            if not unicodedata.combining(c)
        ).split()
    )


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def request_scope(request):
    return _hash(
        {key: request.get(key) for key in ("id", "title", "description", "context", "source_refs")}
    )


def source_version(source):
    return {
        "source_id": source.get("source_id") or source.get("id"),
        **{
            key: source.get(key)
            for key in ("document_id", "version", "sha256", "extraction_revision")
        },
    }


def catalog_audit(request, finding, catalog, *, chunks=(), retrieval_error=None):
    """Auditoría del catálogo y contenido completo autorizado; no incluye sistemas externos."""
    from .source_search_audit import target_document_search

    return {
        **request,
        **target_document_search(
            request, finding, catalog, chunks, retrieval_error=retrieval_error
        ),
    }


def pending_identity(item):
    return (
        item.get("check_key")
        or "check-"
        + _hash({"kind": item.get("kind"), "description": _plain(item.get("description"))})[:24]
    )


def _reason(item):
    text = _plain(item.get("description", ""))
    if re.search(r"(?:cotej\w*|contrast\w*|revis\w*).{0,100}(?:ocr|transcripcion)", text):
        return "transcription"
    if item.get("reason_code") and item["reason_code"] != "specific_gap":
        return item["reason_code"]
    if "extraccion" in text or "completar la lectura" in text:
        return "extraction_error"
    if "transcripcion" in text:
        return "transcription"
    if "vigencia" in text:
        return "validity"
    if re.search(r"version.{0,40}(expedid|firmad|oficial)|es un borrador", text):
        return "issued_version"
    if re.search(r"procedencia|quien verifico|registro de verificacion", text):
        return "provenance"
    if "aplicab" in text or "asunto, persona y periodo" in text:
        return "applicability"
    return "document_search" if item.get("kind") == "document" else "fact_confirmation"


def _linked(item, sources):
    ids = set(item.get("linked_source_ids", []))
    description = _plain(item.get("description", ""))
    for source in sources:
        title = _plain(source.get("title") or source.get("filename") or "")
        filename = _plain(source.get("filename") or "")
        if (title and title in description) or (filename and filename in description):
            ids.add(source.get("source_id") or source.get("id"))
    ids.update(
        source.get("source_id") or source.get("id")
        for source in named_document_candidates(item.get("description", ""), sources)
    )
    references = set(numbered_document_references(item.get("description", "")))
    ids.update(
        source.get("source_id") or source.get("id")
        for source in sources
        if references.intersection(source.get("matched_references", []))
    )
    return sorted(identifier for identifier in ids if identifier)


def _fulfillment(item, request):
    # Sólo actos de esta respuesta. Un justificante de una entrega PASADA sigue
    # siendo evidencia: no se elimina por contener las palabras firma o envío.
    text = _plain(item.get("description", ""))
    if item.get("kind") == "norm" or _reason(item) in {
        "provenance", "issued_version", "transcription", "extraction_error", "validity"
    }:
        return False
    # La tarea principal determina el alcance. Las aclaraciones posteriores
    # «no debe presentarse como realizada» no convierten un trámite futuro en
    # comprobación histórica, ni «respuesta final» convierte un cotejo en trámite.
    task = text.split(". ", 1)[0]
    evidentiary_task = re.match(
        r"^(?:dejar pendiente\s+)?(?:verificar|comprobar|cotejar|contrastar|confirmar|"
        r"acreditar|determinar|identificar|revisar|localizar|obtener|aportar|"
        r"constatar|corroborar)\b", task
    )
    if evidentiary_task and re.search(
        r"\b(?:competencias?|atribuciones?|facultad|autenticidad|integridad|"
        r"procedencia|trazabilidad|autorizacion|habilitacion|justificante|"
        r"identidad|autoria|firmante|autorizad\w*)\b|"
        r"\b(?:anterior(?:es)?|pasad[ao]s?|historic\w*)\b|"
        r"\b(?:se|ya|fue|fueron|ha sido|han sido)\s+(?:efectivamente\s+)?"
        r"(?:firm[oa]\w*|envi[oa]\w*|entreg\w*|expid\w*|exped\w*|realiz\w*|"
        r"ejerc\w*|conclu\w*|efectu\w*)\b",
        task,
    ):
        return False
    if item.get("stage") == "fulfillment":
        return True
    from .request_intent import classify_request_intent

    intent = classify_request_intent(request)
    preparation = re.match(
        r"^(?:dejar pendiente\s+)?(?:asignar|tramitar|preparar|gestionar|coordinar|"
        r"programar|organizar|firmar|enviar|remitir)\b", task
    )
    if preparation and intent["future_action_requested"] and re.search(
        r"\b(?:vigilancia|supervision|supervigilancia)\b|"
        r"\bactuacion de (?:vigilancia o )?verificacion\b|"
        r"\b(?:firma|firmar|envio|enviar|remision|remitir)\b",
        task,
    ):
        return True
    if re.search(
        r"(?:respuesta|oficio|comunicacion) "
        r"(?:final|definitiv\w*|aprobad\w*|a esta peticion|que se emitira)|"
        r"\b(?:esta|presente) (?:respuesta|comunicacion)\b",
        task,
    ):
        return not re.search(r"anterior|pasad[ao]|ya (?:enviad|expedid)|historico", task)
    return bool(
        intent["certification_requested"]
        and re.search(r"certifica|expedirla", text)
        and re.search(r"exped|emit|elabor|prepar|identificar la certificacion.*solicitada", text)
    )


def normalize_item(request, raw, sources=(), search_audit=None):
    item = deepcopy(raw)
    reason = _reason(item)
    links = _linked(item, sources)
    stage = "fulfillment" if _fulfillment(item, request) else "evidence"
    state = "confirmation_pending"
    linked = [s for s in sources if (s.get("source_id") or s.get("id")) in links]
    targets = named_document_candidates(item.get("description", ""), sources)
    references = set(numbered_document_references(item.get("description", "")))
    targets.extend(
        source
        for source in sources
        if references.intersection(source.get("matched_references", []))
    )
    # Un oficio citado como fundamento de una búsqueda no es el anexo buscado.
    located_target = bool(targets)
    unread = [
        s
        for s in linked
        if s.get("extraction_status") in {"pending", "unsupported", "error", "failed"}
    ]
    if (
        reason == "extraction_error"
        and linked
        and not unread
        and all(source.get("extraction_status", "ready") == "ready" for source in linked)
        and re.search(r"cotejar|contrastar|revisar.*transcripcion", _plain(item.get("description")))
    ):
        reason = "transcription"
    if stage == "evidence" and (reason == "extraction_error" or unread):
        state, reason = "analysis_error", "extraction_error"
        if unread:
            item["description"] = (
                "El archivo está conservado, pero no tiene lectura utilizable: "
                + "; ".join(s.get("filename") or s.get("title", "") for s in unread)
                + ". Completar su lectura."
            )
    elif (
        stage == "evidence"
        and item.get("kind") == "document"
        and not located_target
        and reason not in {"transcription", "issued_version", "provenance", "validity"}
    ):
        references = numbered_document_references(item.get("description", ""))
        audit = search_audit or {}
        searched = set(audit.get("negative_sufficient_references", []))
        if (
            references
            and set(references) <= searched
            and audit.get("catalog_complete")
            and not audit.get("access_limited")
            and not audit.get("retrieval_error")
        ):
            state, reason = "document_missing", "document_search"
        else:
            reason = "search_incomplete"
    elif item.get("kind") == "document" and located_target and stage == "evidence":
        if reason not in {"transcription", "issued_version", "provenance", "validity"}:
            reason = "source_identity"
    versions = sorted((source_version(s) for s in linked), key=lambda s: s["source_id"])
    versions = list({v["source_id"]: v for v in versions}.values())
    scope = "document" if reason in DOCUMENT_CHECKS and links else request_scope(request)
    if reason == "transcription" and item.get("linked_chunk_ids"):
        scope = "passage"
    # Comprobaciones generales del mismo archivo se comparten entre preguntas;
    # aplicaciones de un hecho conservan pregunta/contexto y texto concreto.
    identity = {"reason": reason, "stage": stage, "versions": versions, "scope": scope}
    if scope not in {"document", "passage"}:
        identity["description"] = _plain(item.get("description"))
    if reason == "transcription":
        identity["chunks"] = sorted(item.get("linked_chunk_ids", []))
    key = "check-" + _hash(identity)[:24]
    return {
        **item,
        "id": key,
        "check_key": key,
        "reason_code": reason,
        "state": state,
        "stage": stage,
        "blocks_approval": False if stage == "fulfillment" else True,
        "scope_key": scope,
        "request_ids": [request["id"]],
        "linked_source_ids": links,
        "source_versions": versions,
        "resolution": {"status": "open"},
    }


def _information_gap(request, raw, finding):
    """Reutilizar un cotejo declarado para información no exige entregar sus archivos.

    Conserva la propuesta original como diagnóstico y exige confirmar el alcance;
    jamás resuelve el hecho ni convierte el antecedente en comprobación humana.
    """
    from .request_intent import classify_request_intent

    # Una evaluación nueva ya expresa qué afirmación falta y por qué. No sustituir
    # esa brecha concreta por otra confirmación genérica sobre toda la pregunta.
    if finding.get("sufficiency", {}).get("coverage"):
        return raw

    protected = {"transcription", "extraction_error", "issued_version", "provenance", "validity"}
    if (
        raw.get("kind") != "document"
        or _reason(raw) in protected
        or classify_request_intent(request)["intents"] != ["information"]
    ):
        return raw
    ids = set(raw.get("linked_source_ids", []))
    declared = [
        record
        for record in finding.get("verifications", [])
        if record.get("kind") == "antecedent_declared" and record.get("source_id") in ids
    ]
    if not declared:
        return raw
    return {
        **raw,
        "kind": "fact",
        "reason_code": "applicability",
        "original_description": raw.get("description"),
        "description": "Confirmar si la comprobación declarada en el antecedente "
        "cubre exactamente la condición consultada: "
        + str(request.get("description") or request.get("title"))[:1750],
        "reusable_verification_ids": [record["id"] for record in declared if record.get("id")],
    }


def normalize_pending(request, finding, proposed):
    """Conserva metadatos de fuentes y evita reintroducir comprobaciones resueltas."""
    sources = finding.get("supports", [])
    sources = [*sources, *finding.get("candidate_documents", [])]
    resolved = {
        pending_identity(item)
        for item in finding.get("checks", [])
        if item.get("resolution", {}).get("status") == "resolved"
    }
    result = {}
    from .request_intent import fulfillment_actions

    for raw in [
        *finding.get("missing", []),
        *finding.get("actions", []),
        *fulfillment_actions(request),
        *proposed,
    ]:
        item = (
            deepcopy(raw)
            if raw.get("check_key")
            else normalize_item(
                request,
                _information_gap(request, raw, finding),
                sources,
                finding.get("search_audit"),
            )
        )
        if pending_identity(item) not in resolved:
            result.setdefault(pending_identity(item), item)
    return list(result.values())


def apply_evidence_contract(request, finding, candidates=None, *, applications=()):
    """Materializa estados y comprobaciones, sin convertirlos en aprobación."""
    result = deepcopy(finding)
    # La búsqueda dirigida puede encontrar un archivo fuera de los 24 fragmentos.
    # Se conserva como candidato también para el borrador, nunca como cita aprobada.
    documents = result.setdefault("candidate_documents", [])
    document_ids = {item["source_id"] for item in documents}
    for candidate in request.get("catalog_matches", []):
        if candidate["source_id"] not in document_ids:
            documents.append(
                {
                    **deepcopy(candidate),
                    "selected_as_support": False,
                    "chunks": candidate.get("matching_chunks", []),
                    "location_status": "candidate_located",
                }
            )
            document_ids.add(candidate["source_id"])
    sources = [
        *result.get("supports", []),
        *(candidates or []),
        *request.get("catalog_matches", []),
        *result.get("candidate_documents", []),
    ]
    # Preservar metadatos completos cuando el inventario resumido repite la fuente.
    unique = {}
    for source in sources:
        sid = source.get("source_id") or source.get("id")
        unique.setdefault(sid, source)
    sources = list(unique.values())
    audit = request.get("search_audit", result.get("search_audit", {}))
    checks = {}
    from .request_intent import fulfillment_actions

    raw_items = [
        *(result.get("checks") or [*result.get("missing", []), *result.get("actions", [])]),
        *fulfillment_actions(request),
    ]
    for raw in raw_items:
        raw = _information_gap(request, raw, result)
        item = normalize_item(request, raw, sources, audit)
        checks.setdefault(item["check_key"], item)
    for application in applications:
        item = checks.get(application.get("check_key"))
        if not item or not application_matches_check(application, item, request["id"]):
            continue
        item["resolution"] = {
            "status": "resolved",
            "application_id": application["id"],
            "verification_id": application["verification_id"],
            "basis": application.get("basis"),
            "recorded_by": application.get("recorded_by"),
        }
    from .request_intent import classify_request_intent

    result["request_intent"] = classify_request_intent(request)
    result["checks"] = list(checks.values())
    opened = [item for item in checks.values() if item["resolution"]["status"] == "open"]
    result["missing"] = [item for item in opened if item["stage"] == "evidence"]
    result["actions"] = [item for item in opened if item["stage"] == "fulfillment"]
    result["search_audit"] = audit
    states = []
    if any(s.get("category") != "historical_petition" for s in result.get("supports", [])):
        states.append("support_found")
    states.extend(item["state"] for item in result["missing"])
    if result.get("status") == "error":
        states.append("analysis_error")
    if not states:
        states.append("confirmation_pending")
    result["evidence_states"] = list(dict.fromkeys(states))
    if result.get("status") != "error":
        result["status"] = (
            "no_matches"
            if not result.get("supports")
            else "needs_evidence"
            if result["missing"]
            else "references_found"
        )
    return result


def group_checks(results):
    grouped = {}
    for finding in results:
        for item in finding.get("checks", []):
            key = item["check_key"]
            group = grouped.setdefault(
                key, {**deepcopy(item), "request_ids": [], "applications": []}
            )
            group["request_ids"].append(finding["request_id"])
            group["applications"].append(
                {"request_id": finding["request_id"], "resolution": item["resolution"]}
            )
    return list(grouped.values())
