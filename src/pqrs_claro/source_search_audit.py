"""Búsqueda documental acotada en el inventario y texto completo autorizados.

Una ausencia local sólo es evaluable después de consultar ambos. Un resultado
negativo no habla de OnBase ni de archivos institucionales fuera de este catálogo.
Las coincidencias son candidatos para cotejo; no acreditan integridad o entrega.
"""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy

from .request_intent import classify_request_intent
from .source_documents import named_document_candidates, numbered_document_references
from .source_retrieval import source_in_scope

_CATEGORIES = {
    "national_norm", "institutional_norm", "case_evidence", "historical_response",
    "historical_attachment", "historical_petition", "archive_only",
}
_KINDS = (
    r"acta|contrato|resolucion|certificado|certificacion|informe|convenio|"
    r"acuerdo|circular|oficio|respuesta"
)
_HEADER = re.compile(
    rf"^\s*(?P<kind>{_KINDS})s?\s*"
    r"(?:(?:numero|nro\.?|no\.?|num\.?|#)\s*[:.]?\s*)?"
    r"(?P<number>\d+(?:\s*[-–]\s*\d+)*)(?!\d)"
)
_NAMED_HEADER = re.compile(
    rf"^\s*(?P<kind>{_KINDS})s?\b[^\n\d]{{0,100}}?\s"
    r"(?:numero|nro\.?|no\.?|num\.?|#)\s*[:.]?\s*"
    r"(?P<number>\d+(?:\s*[-–]\s*\d+)*)(?!\d)"
)
_BARE_OFFICE_HEADER = re.compile(r"^\s*(?P<number>\d+(?:[-–]\d+){1,3})\s*$")


def _plain(value):
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(value).casefold())
        if not unicodedata.combining(char)
    )


def _same_number(requested, found):
    requested = tuple(str(int(part)) for part in re.findall(r"\d+", requested))
    found = tuple(str(int(part)) for part in re.findall(r"\d+", found))
    if requested == found:
        return True
    if len(requested) == 1:
        # Un número simple puede precisar después su año mediante un cotejo.
        return len(found) >= 2 and requested[0] == found[-2] and len(found[-1]) == 4
    if len(found) < 2:
        return False
    # Los prefijos institucionales no sustituyen número y año exactos.
    return requested[-2:] == found[-2:] and len(requested[-1]) == len(found[-1]) == 4


def _header_references(quote, references):
    result = set()
    for line in _plain(quote).splitlines():
        match = _HEADER.match(line) or _NAMED_HEADER.match(line)
        bare = _BARE_OFFICE_HEADER.match(line) if not match else None
        if not match and not bare:
            continue
        kind = match["kind"] if match else "oficio"
        number = (match or bare)["number"]
        for reference in references:
            wanted_kind, wanted_number = reference.split(" ", 1)
            compatible = kind == wanted_kind or {kind, wanted_kind} <= {"oficio", "respuesta"}
            if compatible and _same_number(wanted_number, number):
                result.add(reference)
    return result


def _email(source, chunks):
    name = _plain(f"{source.get('filename', '')} {source.get('title', '')}").replace("_", " ")
    if re.search(r"\b(?:gmail|fwd|correo|notificacion|remision)\b", name):
        return True
    return any(re.search(
        r"gmail\s*[-:]|https?://mail\.google\.com/|(?m:^\s*(?:para|to|from):)",
        _plain(chunk.get("quote", "")),
    ) for chunk in chunks)


def _references(request, finding):
    texts = []
    if classify_request_intent(request)["document_delivery_requested"]:
        texts.append(request.get("description") or request.get("title") or "")
    for item in [*finding.get("missing", []), *finding.get("checks", [])]:
        if item.get("kind") == "document" and item.get("stage", "evidence") == "evidence":
            texts.append(item.get("description", ""))
    return list(dict.fromkeys(
        reference for text in texts for reference in numbered_document_references(text)
    ))


def target_document_search(request, finding, catalog, chunks, *, retrieval_error=None):
    """Devuelve ``catalog_matches`` y ``search_audit`` sin modificar ninguna entrada.

    ``chunks`` debe ser el snapshot completo, nunca los 24 resultados recuperados.
    Los IDs de versiones y ámbitos ajenos se descartan antes de leer su contenido.
    """
    references = _references(request, finding)
    latest = {}
    for source in catalog:
        if (not source_in_scope(request, source) or source.get("category") not in _CATEGORIES
                or source.get("validity") == "superseded" or source.get("is_latest") is False):
            continue
        sid = source.get("id") or source.get("source_id")
        if not sid:
            continue
        key = source.get("document_id") or sid
        if key not in latest or (source.get("version") or 0) > (latest[key].get("version") or 0):
            latest[key] = {**deepcopy(source), "source_id": sid}
    inventory = {source["source_id"]: source for source in latest.values()}
    grouped = {sid: [] for sid in inventory}
    for chunk in chunks:
        sid = chunk.get("source_id")
        source = inventory.get(sid)
        if not source or not source_in_scope(request, {**source, **chunk}):
            continue
        if any(
            source.get(key) is not None and chunk.get(key) is not None
            and source[key] != chunk[key]
            for key in ("document_id", "version", "sha256", "extraction_revision")
        ):
            continue
        if str(chunk.get("quote") or "").strip():
            grouped[sid].append(chunk)
    unread = [
        sid for sid, source in inventory.items()
        if source.get("extraction_status", "ready") != "ready" or not grouped[sid]
    ]
    matches = {}
    embedded = {reference: [] for reference in references}

    def add(source, reference, basis, chunk=None):
        sid = source["source_id"]
        entry = matches.setdefault(sid, {
            **deepcopy(source), "matched_references": [], "match_basis": [], "matching_chunks": [],
            "identity_status": "candidate_located",
        })
        if reference not in entry["matched_references"]:
            entry["matched_references"].append(reference)
        if basis not in entry["match_basis"]:
            entry["match_basis"].append(basis)
        if chunk and not any(item["chunk_id"] == chunk.get("chunk_id")
                             for item in entry["matching_chunks"]):
            entry["matching_chunks"].append({key: deepcopy(chunk.get(key)) for key in (
                "chunk_id", "page", "line_start", "line_end", "quote", "location_kind",
            )})

    for reference in references:
        for source in named_document_candidates(reference, list(inventory.values())):
            # La identidad por nombre sigue sirviendo aunque la lectura haya fallado.
            add(source, reference, "filename")
    for sid, source in inventory.items():
        message = _email(source, grouped[sid])
        for chunk in grouped[sid]:
            for reference in _header_references(chunk["quote"], references):
                if message or source.get("category") in {"historical_petition", "archive_only"}:
                    # Un encabezado citado dentro de un mensaje exige inspeccionar
                    # el contenedor; no localiza por sí solo el documento adjunto.
                    if sid not in embedded[reference]:
                        embedded[reference].append(sid)
                else:
                    add(source, reference, "document_header", chunk)
    external_requested = bool(re.search(
        r"\b(?:onbase|drive)\b", _plain(" ".join([
            request.get("description", ""),
            *(item.get("description", "") for item in finding.get("missing", [])),
        ])),
    ))
    access_limited = bool(
        request.get("access_limited") or request.get("search_audit", {}).get("access_limited")
        or external_requested
    )
    complete = not unread and not retrieval_error
    targets = []
    for reference in references:
        matched = [
            sid for sid, source in matches.items() if reference in source["matched_references"]
        ]
        targets.append({
            "reference": reference, "matched_source_ids": matched,
            "container_reference_source_ids": embedded[reference],
            "negative_sufficient": bool(
                complete and not access_limited and not matched and not embedded[reference]
            ),
        })
    return {
        "catalog_matches": list(matches.values()),
        "search_audit": {
            "scope": "Catálogo local de las colecciones vinculadas y soportes del expediente",
            "collection_ids": list(request.get("allowed_collection_ids") or []),
            "catalog_count": len(inventory), "catalog_complete": complete,
            "content_search_complete": complete, "full_catalog_text_search": True,
            "targeted_references": references,
            "negative_sufficient_references": [
                target["reference"] for target in targets if target["negative_sufficient"]
            ],
            "matched_source_ids": list(matches), "unread_source_ids": unread,
            "targets": targets, "retrieval_error": retrieval_error,
            "access_limited": access_limited, "external_systems_searched": [],
        },
    }
