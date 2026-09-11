"""Reutilización de comprobaciones: la clave sola nunca autoriza cerrar un pendiente."""

WRITTEN_FACT_REASONS = {"fact_confirmation", "applicability", "fact", "model_fact"}
DOCUMENT_REVIEW_REASONS = {"source_identity", "provenance", "issued_version", "validity"}


def _covers_chunk(passage, chunk_id):
    try:
        source_id, page, start, end = chunk_id.split(":")
        recorded_source = passage["chunk_id"].split(":")[0]
        return (
            source_id == recorded_source and int(page) == passage["page"]
            and passage["line_start"] <= int(start) <= int(end) <= passage["line_end"]
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def application_matches_check(application, check, request_id):
    """Recibe sólo aplicaciones activas del store; vuelve a comprobar su objeto y alcance."""
    if (not isinstance(application, dict) or not isinstance(check, dict)
            or not check.get("check_key") or application.get("check_key") != check["check_key"]
            or request_id not in application.get("request_ids", [])
            or check.get("stage") != "evidence"
            or check.get("state") != "confirmation_pending"
            or not check.get("scope_key")
            or application.get("scope_key") != check["scope_key"]
            or not check.get("reason_code")
            or application.get("check_reason") != check["reason_code"]):
        return False
    record = application.get("record")
    if not isinstance(record, dict) or record.get("id") != application.get("verification_id"):
        return False
    if any(not isinstance(record.get(key), str) or not record[key].strip()
           for key in ("id", "fact", "basis", "recorded_by", "recorded_at")):
        return False
    kind, reason = record.get("kind"), check["reason_code"]
    if kind not in {"human_review", "antecedent_declared"}:
        return False
    method = "human_form" if kind == "human_review" else "model_extraction"
    if record.get("recording_method") != method:
        return False
    if kind == "antecedent_declared" and reason not in WRITTEN_FACT_REASONS:
        return False
    source_id = record.get("source_id")
    if not source_id:
        return (kind == "human_review" and reason in WRITTEN_FACT_REASONS
                and record.get("case_id") == application.get("case_id")
                and record.get("passage") is None)
    if source_id not in check.get("linked_source_ids", []):
        return False
    version = next((item for item in check.get("source_versions", [])
                    if item.get("source_id") == source_id), None)
    if version is None:
        return False
    for field, expected_key in (("document_id", "document_id"), ("version", "version"),
                                ("source_sha256", "sha256")):
        if not record.get(field) or record[field] != version.get(expected_key):
            return False
    if (record.get("extraction_revision") or 0) != (version.get("extraction_revision") or 0):
        return False
    passage = record.get("passage")
    if not isinstance(passage, dict) or not passage.get("quote"):
        return False
    if reason == "transcription":
        chunks = check.get("linked_chunk_ids", [])
        return bool(chunks) and all(_covers_chunk(passage, chunk) for chunk in chunks)
    return reason in (WRITTEN_FACT_REASONS | DOCUMENT_REVIEW_REASONS)
