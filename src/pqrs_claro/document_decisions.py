"""Declaración humana del estado de un archivo, sin certificar sus hechos."""

from .source_assessment import _historical_document_status


def canonical_document_decision(row, item, decision):
    choice = decision.get("document_decision")
    allowed = (
        {"issued", "draft"}
        if item.get("reason_code") == "issued_version"
        else {"provenance_reviewed"}
        if item.get("reason_code") == "provenance"
        else set()
    )
    if choice not in allowed:
        raise ValueError(
            "Esta decisión rápida solo corresponde al estado o procedencia del archivo."
        )
    # Un pasaje explícito tiene prioridad frente a enlaces históricos por número de oficio.
    supports = row.get("available_supports", [])
    chunks = set(item.get("linked_chunk_ids", []))
    targets = [s for s in supports if s["chunk_id"] in chunks]
    if not targets:
        targets = [s for s in supports if s["source_id"] in item.get("linked_source_ids", [])]
    ids = {s["source_id"] for s in targets}
    if ids != {decision.get("document_source_id")}:
        raise ValueError(
            "Selecciona el archivo exacto del pendiente; no se pueden confirmar otras versiones."
        )
    source = targets[0]
    if choice == "issued" and _historical_document_status(source) == "draft":
        raise ValueError(
            "El archivo está identificado como borrador. "
            "Incorpora la versión expedida para sustituirlo."
        )
    note = {
        "issued": (
            "Confirmo que este archivo corresponde a la versión expedida. "
            "Esta declaración no certifica sus hechos ni la entrega de anexos."
        ),
        "draft": (
            "Confirmo que este archivo es un documento de trabajo. "
            "Solo puede utilizarse con esa atribución, "
            "sin presentarlo como respuesta oficial expedida."
        ),
        "provenance_reviewed": (
            "He revisado la procedencia y el contenido de este archivo "
            "para su uso como antecedente. "
            "Esto no certifica todos sus hechos, anexos ni expedición."
        ),
    }[choice]
    return {
        **decision,
        "note": note,
        "cited_chunk_ids": [source["chunk_id"]],
        "cited_fact_ids": [],
        "document_version": {
            k: source.get(k)
            for k in ("source_id", "document_id", "version", "sha256", "extraction_revision")
        },
    }
