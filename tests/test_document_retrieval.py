"""La pregunta repetida no debe desplazar el archivo concreto que se solicita."""

from pqrs_claro.source_retrieval import retrieve


def source(identifier, title, quote, category="historical_attachment"):
    return {
        "chunk_id": f"{identifier}:1:1:3",
        "source_id": identifier,
        "document_id": identifier,
        "title": title,
        "filename": title + ".pdf",
        "quote": quote,
        "category": category,
        "collection_id": "historia",
        "case_id": None,
        "validity": "unknown",
    }


def test_exact_office_is_not_displaced_by_many_copies_of_the_question():
    request = {
        "title": "Oficio 12340001-0098-2024 y soportes",
        "description": "Entregar íntegra y completamente el oficio 12340001-0098-2024, "
        "junto con sus soportes de expedición, radicación y archivo.",
        "case_id": "nuevo",
        "allowed_collection_ids": ["historia"],
    }
    original = source(
        "original",
        "Oficio 0098 Respuesta",
        "12340001-0098-2024\nSeñor solicitante:\nEl comité trató su recurso en sesión ordinaria.",
        "historical_response",
    )
    repeated = [
        source(f"correo-{i}", f"Gmail expediente {i}", request["description"]) for i in range(12)
    ]
    results = retrieve(request, repeated + [original], limit=8)
    assert results[0]["source_id"] == "original"
    assert results[0]["quote"] == original["quote"]
    assert "document_identity_rank" not in original
    assert len(results) == 8


def test_requested_email_with_matching_title_precedes_long_forwarded_mentions():
    request = {
        "title": "Correo de remisión del Oficio 12340001-0098-2024",
        "description": "Entregar el correo electrónico de remisión del Oficio "
        "12340001-0098-2024, incluyendo fecha y hora, remitente y destinatarios.",
        "case_id": "nuevo",
        "allowed_collection_ids": ["historia"],
    }
    original = source(
        "correo-original",
        "NOTIFICACIÓN Oficio 12340001-0098-2024",
        "NOTIFICACIÓN PERSONAL\n1 mensaje\nPara: destinatario@example.test\n"
        "Adjuntamos Oficio 12340001-0098-2024.",
    )
    repeated = [
        source(f"correo-{i}", f"Gmail expediente {i}", request["description"]) for i in range(12)
    ]
    results = retrieve(request, repeated + [original])
    assert results[0]["source_id"] == "correo-original"
    assert results[0]["document_identity_rank"] == 2
    assert retrieve({**request, "allowed_collection_ids": []}, [original]) == []


def test_a_mention_is_not_promoted_as_the_requested_acta():
    request = {
        "title": "Copia del acta 14",
        "description": "Solicito copia del acta 14.",
        "case_id": "nuevo",
        "allowed_collection_ids": ["historia"],
    }
    mention = source("correo", "Gmail sobre acta 14", "ACTA 14\nSolicito copia del acta 14.")
    result = retrieve(request, [mention])
    assert result[0]["document_identity_rank"] == 0


def passage(identifier, page, quote, collection="historia"):
    item = source(identifier, "Respuesta del archivo académico", quote, "historical_response")
    item.update(
        chunk_id=f"{identifier}:{page}:1:3", page=page, line_start=1,
        line_end=len(quote.splitlines()), collection_id=collection,
    )
    return item


def test_answer_after_explicit_boundary_survives_repeated_questions():
    request = {
        "title": "Anexos del acta 14",
        "description": "Entregar íntegra y completamente los anexos del acta 14 "
        "del Consejo de Facultad relacionados con el estudiante.",
        "case_id": "nuevo", "allowed_collection_ids": ["historia"],
    }
    copied = [
        source(f"cadena-{i}", f"Correo trámite {i}", request["description"])
        for i in range(15)
    ]
    petition = passage("respuesta", 1, "PETICIONES\n" + request["description"])
    boundary = passage("respuesta", 2, "Damos respuesta a su solicitud:\nPrimero.")
    answer = passage(
        "respuesta", 3,
        "Los anexos del acta 14 se conservan en el archivo físico del Consejo de Facultad.",
    )
    results = retrieve(request, copied + [petition, boundary, answer], limit=8)
    assert any(row["chunk_id"] == answer["chunk_id"] for row in results)
    selected_answer = next(row for row in results if row["chunk_id"] == answer["chunk_id"])
    assert selected_answer["quote"] == answer["quote"]
    assert len(results) == 8
    assert sum(row["document_id"] == "respuesta" for row in results) <= 2


def test_foreign_answer_boundary_cannot_change_results_or_scores():
    request = {
        "title": "Anexos del acta 14", "case_id": "nuevo",
        "allowed_collection_ids": ["historia"],
    }
    corpus = [
        passage("respuesta", 1, "Solicito los anexos del acta 14."),
        passage("respuesta", 3, "El acta 14 está en archivo."),
    ]
    foreign = passage("respuesta", 2, "Damos respuesta a su solicitud.", "privada")
    assert retrieve(request, corpus + [foreign]) == retrieve(request, corpus)
    assert retrieve({**request, "allowed_collection_ids": []}, corpus + [foreign]) == []


def test_exact_requested_object_keeps_priority_over_answer_branch():
    request = {
        "title": "Copia del oficio 0017-2024", "case_id": "nuevo",
        "allowed_collection_ids": ["historia"],
    }
    original = source(
        "oficio-original", "Oficio 0017-2024", "0017-2024\nSe resolvió la solicitud.",
        "historical_response",
    )
    boundary = passage("otra-respuesta", 1, "Damos respuesta a su solicitud.")
    mention = passage(
        "otra-respuesta", 2,
        "La copia del oficio 0017-2024 se menciona en este trámite anterior.",
    )
    results = retrieve(request, [boundary, mention, original])
    assert results[0]["source_id"] == "oficio-original"


def test_default_budget_is_24_and_explicit_smaller_limit_is_respected():
    request = {
        "title": "Documentos de matrícula", "case_id": "nuevo",
        "allowed_collection_ids": ["historia"],
    }
    corpus = [
        source(f"fuente-{i}", f"Documento {i}", "Registro de matrícula del estudiante.")
        for i in range(30)
    ]
    assert len(retrieve(request, corpus)) == 24
    assert len(retrieve(request, corpus, limit=8)) == 8
    assert len(retrieve(request, corpus, limit=100)) == 24


def test_requested_email_retains_headers_body_and_attachment_list():
    request = {
        "title": "Correo de notificación del Oficio 0017-2024",
        "description": "Entregar fecha, remitente, destinatarios y adjuntos del correo.",
        "case_id": "nuevo", "allowed_collection_ids": ["historia"],
    }
    pieces = [
        "De: archivo@example.test\nPara: estudiante@example.test\nFecha: 3 de mayo de 2024",
        "Notificamos el Oficio 0017-2024, relacionado con la solicitud del estudiante.",
        "Adjuntos:\nOficio 0017-2024.pdf\nHistoria académica.pdf",
    ]
    corpus = []
    for page, quote in enumerate(pieces, 1):
        item = source("notificacion", "Gmail - NOTIFICACIÓN Oficio 0017-2024", quote)
        item.update(chunk_id=f"notificacion:{page}:1:3", page=page)
        corpus.append(item)
    found = retrieve(request, corpus, limit=8)
    assert {row["quote"] for row in found} == set(pieces)
