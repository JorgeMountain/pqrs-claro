from pqrs_claro.source_retrieval import _topic_passages, retrieve


def piece(identity, quote, *, title="Archivo de prueba", category="institutional_norm"):
    return {"chunk_id": identity, "source_id": identity, "document_id": identity,
            "title": title, "quote": quote, "category": category, "case_id": None,
            "page": 1, "line_start": 1, "line_end": 1}


def test_topic_in_body_survives_generic_workflow_and_filename_noise():
    request = {"title": "Informar sobre el trámite de constancia académica",
               "description": "Documentos necesarios, canal de atención y pasos que debe seguir."}
    relevant = piece("rule", "Los certificados de información académica se solicitan en Registro.")
    noise = [piece(str(i), "Pasos del trámite: debe seguir el canal y aportar documentos.",
                   title="Constancia de notificación académica") for i in range(30)]
    result = retrieve(request, [*noise, relevant])
    assert relevant["chunk_id"] in {row["chunk_id"] for row in result}
    assert next(row for row in result if row["chunk_id"] == "rule")["quote"] == relevant["quote"]
    assert _topic_passages(request, noise) == []


def test_phrase_variants_are_candidates_not_changed_quotes_or_duplicate_sources():
    request = {"title": "Constancia académica", "description": "Consulta del trámite."}
    certificate = piece("certificate", "Los certificados académicos se expiden con solicitud.")
    copy = piece("copy", certificate["quote"])
    result = _topic_passages(request, [certificate, copy])
    assert len(result) == 1 and result[0]["quote"] == certificate["quote"]
    assert "role" not in result[0] and "verified" not in result[0]


def test_topic_cannot_introduce_unlinked_or_foreign_sources():
    request = {"title": "Constancia académica", "description": "Información.",
               "case_id": "mine", "allowed_collection_ids": []}
    quote = "Los certificados académicos requieren una solicitud."
    hidden = {**piece("hidden", quote), "collection_id": "private"}
    foreign = {**piece("foreign", quote), "case_id": "other"}
    assert retrieve(request, [hidden, foreign]) == []
