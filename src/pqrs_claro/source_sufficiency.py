"""Suficiencia por afirmación y uso, sin certificar documentos ni aprobar respuestas.

La cobertura es una evaluación atribuida al modelo. Python verifica sus vínculos
literales y limita su efecto: solo las advertencias de catálogo que no afectan al
contenido consultado dejan de convertirse en requisitos de evidencia.
"""

from __future__ import annotations

import re
import unicodedata

from .models import DomainError
from .request_intent import classify_request_intent

POLICY_VERSION = 1

COVERAGE_USES_BY_ROLE = {
    "rule": ["rule"],
    "antecedent": ["attributed_content"],
    "historical_evidence": ["attributed_content", "verified_fact", "official_status"],
    "document": ["attributed_content", "document_delivery", "official_status"],
    "fact": ["attributed_content", "verified_fact", "official_status"],
}


def _plain(text):
    return " ".join("".join(
        c for c in unicodedata.normalize("NFKD", str(text).casefold())
        if not unicodedata.combining(c)
    ).split())


def _literal(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def coverage_citation_errors(selection, candidates):
    """Diagnóstico para un único reintento; nunca acepta ni reescribe citas."""
    index = {item["chunk_id"]: item for item in candidates}
    selected = {item.chunk_id for item in selection.supports}
    errors = []
    for aspect_index, item in enumerate(selection.coverage):
        for citation in item.citations:
            candidate = index.get(citation.chunk_id)
            if candidate is None:
                reason = "unknown_candidate"
            elif citation.chunk_id not in selected:
                reason = "candidate_not_selected_in_supports"
            elif (not _literal(citation.quote)
                  or _literal(citation.quote) not in _literal(candidate["quote"])):
                reason = "quote_not_literal_in_candidate"
            else:
                continue
            error = {"aspect_index": aspect_index, "chunk_id": citation.chunk_id,
                     "reason": reason}
            if reason == "quote_not_literal_in_candidate":
                error.update(submitted_quote=citation.quote, candidate_quote=candidate["quote"])
            errors.append(error)
    return errors


def _requires_more_than_attribution(request):
    intent = classify_request_intent(request)
    if intent["intents"] != ["information"]:
        return True
    text = _plain(request.get("description") or request.get("title") or "")
    return bool(re.search(
        r"\b(?:actualmente|hoy|en la actualidad|este semestre|autenticidad|"
        r"version (?:oficial|expedida|firmada)|copia (?:oficial|autentica|certificada))\b",
        text,
    ))


def validated_coverage(selection, request, supports):
    """Solo admite pasajes literales de respaldos que pasaron los filtros de ámbito."""
    coverage = [item.model_dump() for item in selection.coverage]
    index = {s["chunk_id"]: s for s in supports}
    if selection.coverage_complete and (not coverage or not index):
        raise DomainError("La cobertura completa necesita afirmaciones y pasajes seleccionados.")
    source_uses = {}
    for item in coverage:
        if any(not item[key].strip() for key in ("aspect", "claim", "explanation")):
            raise DomainError("Cada afirmación necesita explicar su alcance y respaldo.")
        if not item["citations"]:
            raise DomainError("Una afirmación respaldada necesita al menos un pasaje literal.")
        for citation in item["citations"]:
            source = index.get(citation["chunk_id"])
            quote = _literal(citation["quote"])
            if not source:
                raise DomainError(
                    "La evaluación citó un fragmento que no incluyó "
                    "entre los soportes seleccionados.")
            if not quote or quote not in _literal(source["quote"]):
                raise DomainError(
                    "La cobertura no coincide literalmente con un pasaje seleccionado.")
            if source.get("category") == "historical_petition":
                raise DomainError("Una petición anterior no acredita una respuesta ni sus hechos.")
            role = source["role"]
            use = item["use"]
            if use not in COVERAGE_USES_BY_ROLE.get(role, []):
                raise DomainError("El respaldo no permite el uso declarado en la cobertura.")
            source_uses.setdefault(source["source_id"], set()).add(use)
    return {
        "policy_version": POLICY_VERSION,
        "coverage_complete": selection.coverage_complete,
        "coverage": coverage,
        "source_uses": {sid: sorted(uses) for sid, uses in source_uses.items()},
        "attribution_only_allowed": not _requires_more_than_attribution(request),
        "assessment_kind": "model_coverage_with_literal_checks",
    }


def metadata_check_required(source, coverage, reason):
    """No necesita expedición oficial para explicar contenido atribuido y localizado."""
    if reason not in {"provenance", "issued_version"}:
        return True
    if not coverage.get("coverage_complete"):
        return True
    uses = coverage.get("source_uses", {}).get(source["source_id"], [])
    # Una fuente contextual no usada por ninguna afirmación no impone condiciones
    # a las afirmaciones que están cubiertas por otros archivos seleccionados.
    if not uses:
        return False
    return not coverage.get("attribution_only_allowed") or set(uses) != {"attributed_content"}


def classify_proposed_gaps(items, supports, coverage):
    """Separa SOLO avisos explícitamente derivados de metadatos; audita la decisión.

Un problema de identidad, contradicción, extracción o documento solicitado nunca
se descarta porque haya una cobertura afirmativa. La cobertura no anula brechas.
"""
    index = {s["source_id"]: s for s in supports}
    retained, observations = [], []
    for item in items:
        ids = item.get("linked_source_ids", [])
        reason = item.get("reason_code")
        metadata_only = item.get("basis") == "metadata_only"
        if (metadata_only and ids and all(sid in index for sid in ids)
                and all(not metadata_check_required(index[sid], coverage, reason) for sid in ids)):
            observations.append({
                "original": item,
                "decision": "non_blocking_metadata",
                "reason": "La respuesta expone contenido atribuido; este metadato de catálogo "
                "no identifica una afirmación sin respaldo ni acredita expedición o autenticidad.",
            })
        else:
            retained.append(item)
    return retained, observations
