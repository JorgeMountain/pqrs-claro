"""Regresiones de contexto y respuestas contiguas con documentos ficticios."""

from pqrs_claro.source_retrieval import RetrievalIndex, retrieve


def chunk(source, page, quote, *, category="historical_response", **extra):
    return dict(
        chunk_id=f"{source}:{page}:1:1", source_id=source, document_id=source,
        page=page, line_start=1, line_end=1, quote=quote, category=category,
        title="Respuesta académica", filename="Respuesta académica.docx",
        collection_id="archivo", validity="not_applicable", case_id=None,
        **extra,
    )


def question(**extra):
    return dict(id="P1", title="Correos sobre la asignatura Máquinas en 2017",
                description="Entregar copias de los correos del profesor dirigidos al solicitante.",
                case_id="actual", allowed_collection_ids=["archivo"], **extra)


def test_question_brings_its_complete_contiguous_answer_and_stops_before_next_question():
    pages = [
        "d) Copias de los correos sobre la asignatura Máquinas en 2017",
        "Respecto de esta solicitud, corresponde consultar el archivo institucional.",
        "No se puede afirmar la inexistencia sin realizar la búsqueda técnica.",
        "Esta conclusión no identifica por sí sola a quien impartió la materia.",
        "e) Copias de los planes de trabajo",
        "El plan pertenece a otro asunto.",
    ]
    corpus = [chunk("oficio", i + 1, text) for i, text in enumerate(pages)]
    corpus += [chunk(f"ruido-{i}", 1, question()["title"], category="historical_petition")
               for i in range(30)]
    results = retrieve(question(), corpus)
    answer = [r for r in results if r.get("adjacent_to")]
    assert {r["page"] for r in answer} >= {2, 3, 4}
    assert all(r["page"] < 5 for r in answer)
    originals = {r["chunk_id"]:r for r in corpus}
    assert all(r["quote"] == originals[r["chunk_id"]]["quote"] for r in results)
    assert len(results) <= 24


def test_context_is_an_additional_query_and_does_not_replace_the_atomic_answer():
    current = chunk("directo", 1, "La asignatura Máquinas tuvo docencia durante 2017.")
    contextual = chunk("contexto", 1, "El profesor Martín Salas pertenece a la sede Norte.")
    q = question(retrieval_context="Martín Salas sede Norte")
    found = retrieve(q, [current, contextual], index=RetrievalIndex([current, contextual]))
    assert {r["source_id"] for r in found} == {"directo", "contexto"}


def test_short_entity_source_survives_many_recipient_lists():
    email = "docente@example.test"
    q = dict(id="P1", title="Titularidad de cuenta institucional",
             description=f"Confirmar si {email} pertenece al profesor Martín Salas.",
             case_id="actual", allowed_collection_ids=["archivo"])
    direct = chunk("diapositiva", 1, f"Martín Salas: {email}", category="historical_attachment")
    lists = [chunk(f"lista-{i}", 1, f"Cco: Martín Salas <{email}>, " + ", ".join(
        f"otro-{j}@example.test" for j in range(20)), category="historical_attachment")
             for i in range(35)]
    assert "diapositiva" in {r["source_id"] for r in retrieve(q, lists + [direct])}


def test_semantic_results_are_filtered_and_keep_the_exact_original_quote():
    accessible = chunk("buena", 1, "La cátedra fue asignada al departamento.")
    foreign = {**chunk("privada", 1, "Dato privado"), "collection_id":"otra"}

    class FakeSemantic:
        def rank(self, query, eligible, limit):
            assert foreign not in eligible
            return [foreign, {**accessible, "quote":"Una afirmación inventada"},
                    {**accessible, "semantic_score":0.9, "category":"national_norm",
                     "document_id":"inventado", "review_status":"reviewed"}]

    result = retrieve(question(), [accessible, foreign], semantic=FakeSemantic())
    assert len(result) == 1
    assert result[0]["quote"] == accessible["quote"]
    assert result[0]["retrieval_channel"] == "semantic"
    assert result[0]["category"] == accessible["category"]
    assert result[0]["document_id"] == accessible["document_id"]
    assert "review_status" not in result[0]


def test_reused_index_cannot_change_scores_when_an_unlinked_collection_is_present():
    good = chunk("buena", 1, "Correos de la asignatura Máquinas.")
    private = {**chunk("privada", 1, "Correos de la asignatura Máquinas."),
               "collection_id":"otra"}
    index = RetrievalIndex([good, private])
    assert retrieve(question(), [good, private], index=index) == retrieve(question(), [good])


def test_adjacency_does_not_cross_originals_or_jump_over_missing_pages():
    anchor = chunk("oficio", 1, "d) Copias de correos de la asignatura Máquinas en 2017")
    later = chunk("oficio", 7, "No se puede afirmar la inexistencia.")
    another = chunk("otro-oficio", 2, "No corresponde a la misma respuesta.")
    assert not any(r.get("adjacent_to") for r in retrieve(question(), [anchor, later, another]))


def test_copy_request_prefers_the_delivery_answer_over_a_similar_factual_question():
    q = {**question(), "title":"Plan de trabajo de Máquinas en 2017",
         "description":"Solicita copia del plan de trabajo aprobado de Máquinas de 2017."}
    corpus = [
        chunk("oficio", 1, "a) ¿Figuró como titular de Máquinas en el plan aprobado de 2017?"),
        chunk("oficio", 2, "Respuesta: Sí, durante ese período."),
        chunk("oficio", 3, "b) Copia del plan de trabajo de Máquinas de 2017"),
        chunk("oficio", 4, "La entrega requiere localizar la copia íntegra en el archivo."),
        chunk("oficio", 5, "c) Copia de otro documento"),
    ]
    result = retrieve(q, corpus)
    answer = next(c for c in result if c["page"] == 4)
    assert answer["adjacent_to"] == corpus[2]["chunk_id"]


def test_question_about_past_email_retrieves_it_without_requesting_delivery():
    from pqrs_claro.source_documents import referenced_document, requested_document

    q = {**question(), "title": "Conocimiento del correo del profesor",
         "description": "Solicita informar si el profesor conoció el correo institucional "
         "enviado el 16 de marzo de 2015 sobre Mecánica de Máquinas."}
    email = {**chunk("correo-original", 1,
                     "Para: estudiante@example.test\n1 mensaje\n"
                     "16 de marzo de 2015. Profesor de Mecánica de Máquinas.",
                     category="historical_attachment"),
             "filename": "Correo de 16 de marzo de 2015.pdf", "title": "Correo institucional"}
    repetitions = [
        chunk(f"peticion-{number}", 1, q["description"], category="historical_petition")
        for number in range(35)
    ]
    result = retrieve(q, repetitions + [email])
    assert requested_document(q) is None
    assert referenced_document(q) == "correo"
    original = next(item for item in result if item["source_id"] == "correo-original")
    assert original["quote"] == email["quote"]
    assert original["document_identity_rank"] > 0
