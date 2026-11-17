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
    # Una referencia explícita a un pasaje identifica SU archivo, no todos los
    # registros con el mismo número de oficio (pueden ser versiones diferentes).
    if _reason(item) in DOCUMENT_CHECKS and item.get("linked_chunk_ids"):
        chunks = set(item["linked_chunk_ids"])
        exact = sorted({s.get("source_id") or s.get("id") for s in sources
                        if s.get("chunk_id") in chunks} - {None})
        if exact:
            return exact
    ids = set(item.get("linked_source_ids", []))
    if ids:
        return sorted(identifier for identifier in ids if identifier)
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
    unique_versions = {}
    for version in versions:
        # El inventario resumido posterior no puede borrar la huella del respaldo.
        unique_versions.setdefault(version["source_id"], version)
    versions = list(unique_versions.values())
    material = item.get("basis") in {"content_gap", "contradiction"} and not (
        reason == "issued_version" and item.get("catalog_check") == "document_status"
    )
    scope = ("document" if reason in DOCUMENT_CHECKS and links and not material
             else request_scope(request))
    if reason == "transcription" and item.get("linked_chunk_ids"):
        scope = "passage"
    # Comprobaciones generales del mismo archivo se comparten entre preguntas;
    # aplicaciones de un hecho conservan pregunta/contexto y texto concreto.
    identity = {"reason": reason, "stage": stage, "versions": versions, "scope": scope}
    if scope not in {"document", "passage"}:
        identity["description"] = _plain(item.get("description"))
    if material:
        # Dos discrepancias del mismo archivo no son un único cotejo humano.
        # Un cambio de afirmación tampoco puede reutilizar su aprobación anterior.
        identity["material"] = {
            field: _plain(item.get(field, ""))
            for field in ("description", "affected_claim", "why_unresolved", "basis")
        }
        identity["chunks"] = sorted(item.get("linked_chunk_ids", []))
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


def _complete_versions(item):
    versions = item.get("source_versions", [])
    if not versions or not all(
        version.get("source_id") and version.get("document_id")
        and version.get("version") is not None
        and re.fullmatch(r"[0-9a-fA-F]{64}", str(version.get("sha256", "")))
        for version in versions
    ):
        return None
    return sorted(versions, key=lambda version: version["source_id"])


def _document_authentication(item, request, sources, *, allow_resolved=False):
    """Conservative purpose check; neither a reason code nor a signature suffices."""
    if (
        item.get("basis") not in {"content_gap", "contradiction"}
        or item.get("stage") != "evidence"
        or item.get("state") != "confirmation_pending"
        or item.get("resolution", {}).get("status") not in (
            {"open", "resolved"} if allow_resolved else {"open"}
        )
        or item.get("scope_key") != request_scope(request)
        or item.get("request_ids") != [request["id"]]
        or item.get("reason_code") not in {
            "provenance", "source_identity", "issued_version", "applicability", "fact_confirmation"
        }
    ):
        return False
    claim = _plain(item.get("affected_claim", ""))
    description = _plain(item.get("description", ""))
    provenance = r"\b(?:procedencia|procede[n]?|origen|trazabilidad)\b"
    authentic = r"\bautentic\w*\b"
    # Autenticar una firma o un sello aislados no acredita el origen del archivo.
    component_only = re.search(
        r"\bautenticidad de (?:la |el )?(?:firma|sello)\b|"
        r"\b(?:firma|sello)\b.{0,70}\b(?:es|sea|son|sean)\s+autentic\w*", claim
    )
    documentary = bool(re.search(r"\b(?:copia|ejemplar|archivo|documento|original)\b", claim))
    if not documentary:
        linked = set(item.get("linked_source_ids", []))
        documentary = any(
            (source.get("source_id") or source.get("id")) in linked
            for source in named_document_candidates(claim, sources)
        )
    purpose = (
        re.search(provenance, claim)
        and re.search(provenance + r"|\bregistro de ingreso\b|\bcadena de custodia\b", description)
    ) or (not component_only and re.search(authentic, claim)
          and re.search(authentic, description))
    return bool(documentary and purpose)


def _consolidate_provenance(request, items, sources, decisions=(), *, resolved_checks=()):
    """Absorb only local catalog redundancy; never resolve a material check."""
    decisions = deepcopy(list(decisions))
    catalog_originals = {
        row["original"]["check_key"]: row["original"] for row in decisions
        if row.get("decision") == "covered_by_specific_check"
        and row.get("original", {}).get("catalog_check") == "review_status"
        and row["original"].get("check_key")
    }
    catalog_originals.update(
        (item["check_key"], item) for item in items
        if item.get("catalog_check") == "review_status"
    )
    material = [item for item in items if _document_authentication(item, request, sources)]
    reviewed = [item for item in [*items, *resolved_checks]
                if item.get("resolution", {}).get("status") == "resolved"
                and item["resolution"].get("application_id")
                and item["resolution"].get("verification_id")
                and _document_authentication(item, request, sources, allow_resolved=True)]
    retained = []
    for item in items:
        versions = _complete_versions(item)
        covering = []
        if (item.get("check_key") in catalog_originals and versions
            and item.get("reason_code") == "provenance"
            and item.get("basis") == "metadata_only"
            and item.get("stage") == "evidence"
            and item.get("scope_key") == "document"
            and item.get("request_ids") == [request["id"]]
            and item.get("resolution", {}).get("status") == "open"):
            covering = sorted({specific["check_key"] for specific in material
                               if _complete_versions(specific) == versions})
            # Solo una relación auditada ANTES de la revisión permite omitir su
            # genérico al redactar. No trasladar una aprobación a otra obligación.
            prior = {key for row in decisions
                     if row.get("decision") == "covered_by_specific_check"
                     and row.get("original", {}).get("check_key") == item["check_key"]
                     for key in row.get("covering_check_keys", [])}
            covering = sorted(set(covering) | {
                specific["check_key"] for specific in reviewed
                if specific["check_key"] in prior and _complete_versions(specific) == versions
            })
        if not covering:
            retained.append(item)
            continue
        if not any(row.get("decision") == "covered_by_specific_check"
                   and row.get("original", {}).get("check_key") == item["check_key"]
                   and row.get("covering_check_keys") == covering for row in decisions):
            decisions.append({
                "decision": "covered_by_specific_check",
                "original": deepcopy(catalog_originals[item["check_key"]]),
                "covering_check_keys": covering,
                "reason": "El cotejo concreto de autenticidad conserva abierta la revisión "
                          "de procedencia del mismo archivo y versión; no se añade otra tarea "
                          "por el estado del catálogo ni se declara verificación realizada.",
            })
    return retained, decisions


def normalize_pending(request, finding, proposed):
    """Conserva metadatos de fuentes y evita reintroducir comprobaciones resueltas."""
    sources = finding.get("supports", [])
    sources = [*sources, *finding.get("candidate_documents", [])]
    resolved = {
        pending_identity(item)
        for item in finding.get("checks", [])
        if item.get("resolution", {}).get("status") == "resolved"
    }
    items = []
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
            items.append(item)
    items, _ = _consolidate_provenance(
        request, items, sources, finding.get("gap_decisions", []),
        resolved_checks=finding.get("checks", []),
    )
    result = {}
    for item in items:
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
    items = []
    from .request_intent import fulfillment_actions

    raw_items = [
        *(result.get("checks") or [*result.get("missing", []), *result.get("actions", [])]),
        *fulfillment_actions(request),
    ]
    for raw in raw_items:
        raw = _information_gap(request, raw, result)
        item = normalize_item(request, raw, sources, audit)
        items.append(item)
    for application in applications:
        for item in items:
            if not application_matches_check(application, item, request["id"]):
                continue
            item["resolution"] = {
                "status": "resolved",
                "application_id": application["id"],
                "verification_id": application["verification_id"],
                "basis": application.get("basis"),
                "recorded_by": application.get("recorded_by"),
            }
    retained, decisions = _consolidate_provenance(
        request, items, sources, result.get("gap_decisions", [])
    )
    if decisions:
        result["gap_decisions"] = decisions
    removed = {item["check_key"] for item in items} - {item["check_key"] for item in retained}
    descriptions = {item.get("description") for item in items if item["check_key"] in removed}
    if descriptions:
        result["warnings"] = [warning for warning in result.get("warnings", [])
                              if warning not in descriptions]
    checks = {}
    for item in retained:
        checks.setdefault(item["check_key"], item)
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
