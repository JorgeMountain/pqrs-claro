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


def _material_signature_task(item):
    """Recognize a declared material check, never infer one from a copy request."""
    if item.get("basis") not in {"content_gap", "contradiction"}:
        return False
    task = _plain(item.get("description", "")).split(". ", 1)[0]
    check = re.match(
        r"^(?:(?:completar|realizar|efectuar|terminar)\s+(?:(?:el|un)\s+)?"
        r"(?:cotejo|contraste|verificacion|comprobacion|validacion)|"
        r"cotejar|contrastar|verificar|comprobar|corroborar|validar)\b"
        r".{0,150}\b(?:firma|firmas|trazo|firmante)\b", task,
    )
    if not check:
        return False
    before_signature = re.split(r"\b(?:firma|firmas|trazo|firmante)\b", check.group(), 1)[0]
    if re.search(r"\b(?:competencia|facultad|vigencia|integridad|procedencia|"
                 r"contenido|trazabilidad)\b", before_signature):
        return False  # A different material check must keep its own purpose/identity.
    # Checking that a future response gets signed is a delivery task. The rule
    # concerns a signature already present in a source, not the future copy.
    subject = task[:check.end() + 90].split(" y preparar", 1)[0]
    if re.search(r"\b(?:respuesta|copia|certificacion|documento)\s+"
                 r"(?:futur\w*|nuev\w*|que se (?:emitira|expedira))\b", subject):
        return False
    why = _plain(item.get("why_unresolved", ""))
    if re.search(r"\bno\s+(?:se\s+)?(?:requiere|necesita)\s+(?:un\s+)?cotejo\b|"
                 r"\bno\s+(?:hay|existe)\s+(?:ninguna\s+)?(?:duda|discrepancia)\b", why):
        return False
    existing = (re.search(r"\b(?:original|reproduccion|ejemplar|registro|expedicion|"
                          r"documento|oficio|informe)\b", why)
                or bool(item.get("linked_source_ids") or item.get("linked_chunk_ids")))
    material = re.search(
        r"\b(?:firma|trazo)\b.{0,100}\b(?:ilegible|borros\w*|distint\w*|diferent\w*|"
        r"no coincide\w*|no corresponde\w*|no permite\w*)\b|"
        r"\b(?:no|sin)\b.{0,80}\b(?:cotejo|contraste|verificacion|validacion|"
        r"verificarse|validarse)\b|"
        r"\b(?:cotejo|contraste|validacion|certificado|sello de tiempo)\b"
        r".{0,60}\b(?:pendiente|no realizado|no consta|no verificad\w*)\b",
        why,
    )
    return bool(existing and material)


def _separate_signature_task(request, raw):
    """Separate an explicitly mixed material check from already requested delivery.

    The generic delivery action is emitted by fulfillment_actions; duplicating it
    here would recreate the original problem. Keep the discarded conjunction as
    audit data, not as another control or an automatic human approval.
    """
    if not _material_signature_task(raw):
        return deepcopy(raw)
    item = deepcopy(raw)
    declared_identity = raw.get("reason_code") in {"provenance", "source_identity"}
    item["stage"] = "evidence"
    if not declared_identity:
        item.update(kind="fact", reason_code="fact_confirmation")
    from .request_intent import fulfillment_actions

    delivery = [action for action in fulfillment_actions(request)
                if action["reason_code"] in {"document_delivery", "certification_preparation"}]
    description = str(item.get("description", ""))
    boundary = re.search(
        r"\s+(?:y(?:\s+luego)?|e|para\s+luego)\s+"
        r"(?=(?:preparar|entregar|expedir|enviar|remitir)\b)|;\s*"
        r"(?=(?:preparar|entregar|expedir|enviar|remitir)\b)",
        description, re.IGNORECASE,
    )
    if delivery and boundary:
        task, future = description[:boundary.start()].strip(), description[boundary.end():].strip()
        if task and re.search(r"\b(?:copia|archivo|documento|ejemplar|certificaci[oó]n)\b",
                              future, re.IGNORECASE):
            item.update(description=task,
                        original_description=item.get("original_description", description))
            if not declared_identity:
                item["affected_claim"] = task
            item["separated_fulfillment"] = {
                "description": future,
                "represented_by": [action["reason_code"] for action in delivery],
            }
    return item


def requested_delivery_task(request, item):
    """A declared future delivery keeps its purpose despite a condition of authenticity."""
    from .request_intent import classify_request_intent

    if (item.get("stage") != "fulfillment"
            or item.get("basis") not in {None, "unspecified", "metadata_only"}
            or item.get("reason_code") not in {
                None, "specific_gap", "requested_followup", "document_delivery"}
            or not classify_request_intent(request)["document_delivery_requested"]):
        return False
    task = re.split(r"\b(?:una vez|despues de|tras|siempre que|cuando)\b",
                    _plain(item.get("description", "")).split(". ", 1)[0], 1)[0]
    return bool(
        re.match(r"^(?:preparar|certificar|expedir|entregar|remitir|enviar|adjuntar|"
                 r"proporcionar|facilitar)\b", task)
        and re.search(r"\b(?:copia|copias|archivo|archivos|documento|documentos|"
                      r"ejemplar|ejemplares|ficha)\b", task)
        and not re.search(r"\b(?:cotejar|contrastar|verificar|validar|acreditar|"
                          r"confirmar|comprobar)\b", task)
    )


def _fulfillment(item, request):
    # Sólo actos de esta respuesta. Un justificante de una entrega PASADA sigue
    # siendo evidencia: no se elimina por contener las palabras firma o envío.
    text = _plain(item.get("description", ""))
    if _material_signature_task(item):
        return False
    if requested_delivery_task(request, item):
        return True
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
    links = _linked(raw, sources)
    item = _separate_signature_task(request, raw)
    delivery = requested_delivery_task(request, item)
    if delivery:
        item["reason_code"] = "document_delivery"
    reason = "document_delivery" if delivery else _reason(item)
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
    if reason == "requested_followup":
        # A chunk may announce several future events. A closure of one literal
        # passage must not close another merely because the summary is equal.
        identity["followup"] = {
            "requirement_ids": sorted(item.get("requirement_ids", [])),
            "passages": sorted(item.get("followup_passages", []),
                               key=lambda row: (row.get("chunk_id", ""), row.get("quote", ""))),
            "claims": sorted(item.get("followup_claims", [])),
        }
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


def _copy_delivery_signature(text):
    """Literal object and explicit modality; uncertainty cannot prove coverage."""
    text = re.split(r"\b(?:una vez|despues de|tras|siempre que|cuando)\b", _plain(text), 1)[0]
    copies = list(re.finditer(r"\bcopia\b", text))
    if not copies:
        return None
    if len(copies) != 1:
        return set(), ("ambiguous", text)
    tail = text[copies[0].end():].strip()
    mode = re.match(r"^(simple|certificada|autenticada)\b\s*", tail)
    modes = {mode[1]} if mode else set()
    if re.search(r"\bcertificar\b", text):
        modes.add("certificada")
    if mode:
        tail = tail[mode.end():]
    object_match = re.match(r"^(?:del|de(?:\s+(?:el|la))?)\s+(.+)", tail)
    if not object_match:
        anaphoric = re.fullmatch(r"(?:solicitada|pedida|correspondiente)[\s,.]*", tail)
        return modes, None if anaphoric else ("ambiguous", tail)
    target = re.split(r"[,;!?]|\.(?:\s|$)", object_match[1], 1)[0].strip()
    # Availability/location describes where this same current source is held,
    # not a longer object name. Do not trim arbitrary prepositions or quoted titles.
    if not re.search(r'["«»“”]', target):
        target = re.split(r"\s+(?:disponible|conservad[oa])\s+en\b", target, 1)[0]
    references = tuple(sorted(numbered_document_references(target)))
    return modes, ("numbered", references) if references else ("literal", target)


def _same_requested_copy(delivery_text, represented):
    requested = _copy_delivery_signature(delivery_text)
    if not requested or not requested[1] or requested[1][0] == "ambiguous":
        return False
    modes, target = requested
    for gap in represented:
        specifics = [signature for key in ("description", "affected_claim")
                     if (signature := _copy_delivery_signature(gap.get(key, "")))]
        objects = [obj for _, obj in specifics if obj is not None]
        declared_modes = set().union(*(mode for mode, _ in specifics))
        if objects and all(obj == target for obj in objects) and declared_modes == modes:
            return True
    return False


def _delivery_is_represented(request, finding):
    """Only exact requirement/gap/current-action links can replace inferred delivery."""
    from .request_intent import classify_request_intent, delivery_request_text
    from .request_requirements import build_requirements
    from .source_retrieval import source_in_scope

    requirements = request.get("request_requirements") or build_requirements(request)
    requested = [r for r in requirements if classify_request_intent(
        {"description": r.get("text", "")})["document_delivery_requested"]]
    if not requested:
        return False
    sufficiency = finding.get("sufficiency") or {}
    gaps = sufficiency.get("evaluated_gaps", [])
    reviews = sufficiency.get("requirement_checks", [])
    known = [*finding.get("checks", []), *finding.get("missing", []),
             *finding.get("actions", [])]
    sources = {s["chunk_id"]: s for s in finding.get("supports", [])
               if s.get("chunk_id") and source_in_scope(request, s)
               and s.get("is_latest") is not False and s.get("validity") != "superseded"
               and s.get("extraction_status", "ready") == "ready"}
    description = _plain(request.get("description") or request.get("title") or "")
    for requirement in requested:
        if _plain(requirement.get("text", "")) not in description:
            return False
        matching = [r for r in reviews if r.get("requirement_id") == requirement.get("id")]
        if len(matching) != 1:
            return False
        indexes = matching[0].get("missing_indexes", [])
        if not indexes:
            # Complete content may identify a copy without turning its future
            # delivery into missing evidence. Reuse that existing exact path;
            # never rewrite the reader's supported state or missing indexes.
            coverage = sufficiency.get("coverage", [])
            covered = matching[0].get("coverage_indexes", [])
            if (len(requested) != 1 or matching[0].get("status") != "supported"
                    or len(covered) != 1 or type(covered[0]) is not int
                    or not 0 <= covered[0] < len(coverage)):
                return False
            row = coverage[covered[0]]
            citations = row.get("citations", [])
            if row.get("use") != "attributed_content" or not citations:
                return False
            for citation in citations:
                source = sources.get(citation.get("chunk_id"))
                quote = citation.get("quote")
                if (not source or source.get("role") == "rule" or not isinstance(quote, str)
                        or not quote.strip() or quote not in source.get("quote", "")):
                    return False
            indexes = [i for i, gap in enumerate(gaps) if requested_delivery_task(request, gap)]
            identities = {
                _hash({key: item.get(key) for key in (
                    "description", "affected_claim", "linked_chunk_ids", "source_versions")})
                for item in known if requested_delivery_task(request, item)
            }
            if (len(indexes) != 1 or len(identities) != 1
                    or set(gaps[indexes[0]].get("source_chunk_ids", []))
                    != {citation["chunk_id"] for citation in citations}):
                return False
        represented = []
        for index in indexes:
            if type(index) is not int or not 0 <= index < len(gaps):
                return False
            gap = gaps[index]
            chunks = set(gap.get("source_chunk_ids", []))
            if (not requested_delivery_task(request, gap)
                    or not chunks or not chunks <= sources.keys()):
                continue
            versions = sorted({sources[c]["source_id"]: source_version(sources[c])
                               for c in chunks}.values(), key=lambda row: row["source_id"])
            for item in known:
                if (not requested_delivery_task(request, item)
                        or gap.get("description") != item.get("description")
                        or gap.get("affected_claim") != item.get("affected_claim")
                        or chunks != set(item.get("linked_chunk_ids", []))):
                    continue
                previous = sorted(item.get("source_versions", []),
                                  key=lambda row: row.get("source_id", ""))
                if (previous and previous != versions) or (
                        not previous and item.get("resolution", {}).get("status") == "resolved"):
                    continue
                represented.append(gap)
                break
        if not represented:
            return False
        delivery_text = delivery_request_text({"description": requirement["text"]})
        references = set(numbered_document_references(delivery_text))
        if (len(references) > 1 or "," in delivery_text
                or re.search(r"\b(?:copias|archivos|documentos|ejemplares)\b", delivery_text)
                or re.search(r"\b(?:y|e)\s+(?!(?:indiqu\w*|inform\w*|confirm\w*|"
                             r"expliqu\w*|aclar\w*)\b)", delivery_text)):
            # Lists and coordinated objects need an explicit inventory to prove
            # completeness. Keep the generic obligation when that is absent.
            return False
        if not _same_requested_copy(delivery_text, represented):
            return False
    return True


def _requested_actions(request, finding):
    from .request_intent import fulfillment_actions
    from .requested_followup import requested_followups

    followups = requested_followups(request, finding, include_existing=True)
    specific_supervision = any(item.get("replaces_generic_supervision") for item in followups)
    specific_delivery = _delivery_is_represented(request, finding)
    # Only replace a newly inferred generic action, never a stored control or a
    # human resolution. A distinct supervision mandate remains independent.
    generic = [item for item in fulfillment_actions(request)
               if not (specific_supervision and item["reason_code"] == "supervision")
               and not (specific_delivery and item["reason_code"] == "document_delivery")]
    return [*generic, *followups]


def pending_registry(request, finding):
    """Una vista de los controles conciliados, incluidos los ya resueltos.

    ``checks`` conserva identidad, alcance y resolución. Las vistas antiguas se
    admiten para compatibilidad y para no perder controles nuevos todavía no
    conciliados; nunca sustituyen un registro conocido por una copia parcial.
    La vigencia de las fuentes y las aplicaciones se valida antes, en el contrato
    de evidencias. Esta función no aprueba ni reinterpreta comprobaciones.
    """
    sources = [*finding.get("supports", []), *finding.get("candidate_documents", [])]
    registry = {}
    for raw in [
        *finding.get("checks", []),
        *finding.get("missing", []),
        *finding.get("actions", []),
        *_requested_actions(request, finding),
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
        registry.setdefault(pending_identity(item), item)
    items, _ = _consolidate_provenance(
        request, list(registry.values()), sources, finding.get("gap_decisions", [])
    )
    return items


def normalize_pending(request, finding, proposed):
    """Deriva pendientes abiertos y reutiliza referencias sin cambiar su alcance."""
    from .models import DomainError

    sources = [*finding.get("supports", []), *finding.get("candidate_documents", [])]
    registry = {pending_identity(item): item for item in pending_registry(request, finding)}
    resolved = {key for key, item in registry.items()
                if item.get("resolution", {}).get("status") == "resolved"}
    items = [deepcopy(item) for key, item in registry.items() if key not in resolved]
    for raw in proposed:
        references = raw.get("existing_check_keys", [])
        if any(key not in registry for key in references):
            raise DomainError(
                "El pendiente referencia una comprobación que no corresponde a la pregunta."
            )
        if references:
            # El registro ya está incluido. Una paráfrasis no puede reabrirlo,
            # convertirlo en entrega ni reemplazar su alcance por otro texto.
            continue
        item = (deepcopy(raw) if raw.get("check_key") else normalize_item(
            request, _information_gap(request, raw, finding), sources,
            finding.get("search_audit"),
        ))
        key = pending_identity(item)
        if key not in resolved:
            items.append(deepcopy(registry.get(key, item)))
    items, _ = _consolidate_provenance(
        request, items, sources, finding.get("gap_decisions", []),
        resolved_checks=list(registry.values()),
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
    raw_items = [
        *(result.get("checks") or [*result.get("missing", []), *result.get("actions", [])]),
        *_requested_actions(request, result),
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
