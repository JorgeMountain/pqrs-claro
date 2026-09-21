"""Body passages stay discoverable under unrelated historical correspondence."""

from copy import deepcopy

import pytest

from pqrs_claro.source_retrieval import retrieve


def piece(source, page, text, **extra):
    return dict(
        source_id=source,
        document_id=source,
        chunk_id=f"{source}:{page}",
        title="Guía de admisiones 2027",
        filename="guia.pdf",
        quote=text,
        page=page,
        line_start=1,
        line_end=1,
        category="institutional_norm",
        collection_id="admisiones",
        case_id=None,
        validity="current",
        **extra,
    )


def request(title, description):
    return dict(
        id="P1",
        title=title,
        description=description,
        case_id="test",
        allowed_collection_ids=["admisiones", "historia"],
        context={"subject": "Consulta sobre el examen de admisión 2027"},
    )


@pytest.mark.parametrize(
    "title,description,answer",
    [
        (
            "Competencias y porcentajes",
            "Qué competencias se evalúan en el examen de admisión 2027",
            "Competencia lectora y competencia en razonamiento lógico. Cada una vale el 50%.",
        ),
        (
            "Tiempo para resolver el examen",
            "Cuánto tiempo tendré para resolver el examen",
            "El examen tendrá una duración máxima de tres horas.",
        ),
        (
            "Impresión de credencial",
            "Dónde se puede imprimir la credencial",
            "Puede imprimir la credencial en el portal de inscripciones.",
        ),
    ],
)
def test_subject_locates_document_and_body_answers_without_rewriting(title, description, answer):
    q = request(title, description)
    cover = piece("guia", 1, "ADMISIONES. Guía para aspirantes nuevos 2027.")
    expected = piece("guia", 4, answer)
    noise = [
        {
            **piece(f"old-{i}", 1, description),
            "title": "Respuesta a petición antigua",
            "category": "historical_response",
            "collection_id": "historia",
        }
        for i in range(40)
    ]
    corpus = [*noise, cover, expected]
    before = deepcopy(corpus)
    rows = retrieve(q, corpus)
    selected = next(row for row in rows if row["chunk_id"] == expected["chunk_id"])
    assert selected["retrieval_channel"] == "document_content"
    assert selected["quote"] == answer
    assert selected["page"] == 4
    assert corpus == before
    assert len(rows) <= 24


@pytest.mark.parametrize(
    "changes",
    [
        {"collection_id": "private"},
        {"case_id": "other"},
        {"validity": "superseded"},
        {"category": "archive_only"},
    ],
)
def test_document_content_never_expands_authorized_scope(changes):
    q = request("Tiempo del examen", "Tiempo para resolver el examen")
    foreign = {**piece("foreign", 4, "Duración del examen: tres horas."), **changes}
    rows = retrieve(q, [foreign, piece("public", 1, "Portada de la guía de admisiones 2027")])
    assert all(row["source_id"] != "foreign" for row in rows)


def test_metadata_match_alone_does_not_promote_body_as_answer():
    from pqrs_claro.source_retrieval import _document_content

    q = request("Duración", "Duración máxima")
    assert _document_content(q, [piece("guia", 1, "PORTADA")]) == []


def test_document_content_respects_small_limit_and_has_no_duplicate_chunks():
    q = request("Tiempo del examen", "Tiempo para resolver el examen")
    corpus = [piece("guia", i, "La duración del examen es tres horas.") for i in range(1, 8)]
    rows = retrieve(q, corpus, limit=1)
    assert len(rows) == 1


@pytest.mark.parametrize("date", ["26 y 27 de octubre de 2026", "26/10/2026"])
def test_calendar_reserves_original_dated_passage_among_generic_matches(date):
    q = request("Fechas de presentación del examen", "Fechas previstas en el calendario del examen")
    expected = piece("guia", 44, f"El examen de admisión se efectuará el {date}.")
    noise = [
        piece(
            f"noise-{i}",
            5,
            "Fechas previstas para presentación del examen. "
            "No se permite cambiar fecha y hora. Calendario de presentación del examen.",
        )
        for i in range(35)
    ]
    rows = retrieve(q, [*noise, expected])
    found = next(r for r in rows if r["chunk_id"] == expected["chunk_id"])
    assert found["retrieval_channel"] == "calendar"
    assert found["quote"] == expected["quote"]
    assert (found["page"], found["line_start"], found["line_end"]) == (44, 1, 1)
    assert len(rows) <= 24


@pytest.mark.parametrize(
    "changes",
    [
        {"collection_id": "private"},
        {"case_id": "other"},
        {"validity": "superseded"},
        {"category": "archive_only"},
    ],
)
def test_calendar_never_bypasses_scope(changes):
    q = request("Fechas del examen", "Cuándo se presenta el examen")
    row = {**piece("foreign", 44, "El examen será el 26 de octubre de 2026."), **changes}
    assert retrieve(q, [row]) == []


def test_calendar_requires_a_nearby_event_and_does_not_interpret_bare_year():
    from pqrs_claro.source_retrieval import _date_passages

    q = request("Fechas del examen", "Fechas previstas para el examen")
    unrelated = piece(
        "guia", 1, "Impreso el 10 de mayo de 2026. " + "portada " * 100 + "Examen de admisión."
    )
    year = piece("guia", 2, "Examen de admisión 2027-1. Ley 30 de 1992.")
    assert _date_passages(q, [unrelated, year]) == []
    q = request("Duración del examen", "Cuánto dura el examen")
    assert _date_passages(q, [piece("guia", 44, "Examen: 26 de octubre de 2026.")]) == []


def test_calendar_honors_limit_and_deduplicates_other_channels():
    q = request("Fechas del examen", "Fechas previstas para el examen")
    rows = retrieve(q, [piece("guia", 44, "Examen: 26 de octubre de 2026.")], limit=1)
    assert len(rows) == 1


def test_body_answer_survives_two_higher_ranked_portal_references():
    from pqrs_claro.source_retrieval import _rank, _search_words

    q = request(
        "Pruebas y ponderación del examen",
        "Qué pruebas debe presentar en el examen y qué peso tiene cada una",
    )
    expected = piece(
        "guia",
        4,
        "Competencia lectora. Prueba 2: razonamiento lógico. "
        "Cada aspirante debe presentar ambas pruebas; cada una tiene un valor del 50%.",
    )
    corpus = [
        piece(
            "guia",
            5,
            "Pruebas y ponderación del examen. Qué pruebas debe presentar "
            "y qué peso tiene cada una: consulte el portal.",
        ),
        piece(
            "guia",
            31,
            "Pruebas y ponderación del examen. Qué pruebas debe presentar "
            "y qué peso tiene cada una: consultar metodología web.",
        ),
        expected,
    ]
    query = _search_words(q["title"] + " " + q["description"], expand=True)
    ranked = _rank(
        {}, [{**c, "title": "", "quote": _search_words(c["quote"])} for c in corpus], query=query
    )
    assert ranked[2]["chunk_id"] == expected["chunk_id"]
    rows = retrieve(q, corpus)
    assert any(
        r["chunk_id"] == expected["chunk_id"] and r["quote"] == expected["quote"] for r in rows
    )


def test_semantic_passage_keeps_room_after_document_body_reservation():
    q = request("Pruebas y ponderación", "Pruebas y ponderación del examen")
    corpus = [
        piece("guia", i, "Pruebas y ponderación del examen: consulte metodología.")
        for i in range(1, 5)
    ]
    expected = piece("guia", 9, "Competencia lectora y razonamiento lógico, cada una vale 50%.")

    class Semantic:
        def rank(self, query, eligible, limit):
            return [{**expected, "semantic_score": 0.99}]

    rows = retrieve(q, [*corpus, expected], semantic=Semantic())
    assert any(
        r["chunk_id"] == expected["chunk_id"] and r["retrieval_channel"] == "semantic" for r in rows
    )
    assert len(rows) <= 24
    assert len({r["chunk_id"] for r in rows}) == len(rows)


def test_calendar_event_proximity_beats_dated_regulations_and_registration():
    q = request(
        "Fechas de presentación del examen",
        "Solicita informar las fechas previstas para la presentación del examen "
        "en la convocatoria correspondiente al período 2027-1.",
    )
    expected = piece(
        "guia",
        3,
        "1. Calendario\nInscripciones\n14 de septiembre de 2026\n"
        "Examen de\n26 y 27 de octubre de 2026\nAdmisión\n"
        "Publicación de resultados\n11 de noviembre de 2026",
    )
    noise = [
        piece(
            "guia",
            42,
            "Para la presentación del examen se requiere braille. "
            "Solicitar ajustes antes de finalizar el periodo de inscripciones, "
            "14 de septiembre de 2026, con certificado médico.",
        ),
        piece(
            "guia",
            27,
            "La presentación del examen de admisión se rige por la "
            "Ley 1084 del 4 de agosto de 2006. Aspirantes especiales de convocatoria 2027-1.",
        ),
        piece(
            "guia", 1, "ADMISIONES. Guía de presentación del examen para aspirantes nuevos 2027-1."
        ),
    ]
    rows = retrieve(q, [*noise, expected])
    assert rows[0]["chunk_id"] == expected["chunk_id"]
    assert rows[0]["retrieval_channel"] == "calendar"
    assert rows[0]["quote"] == expected["quote"]


def test_when_question_recovers_calendar_without_word_fecha():
    q = request("Presentación del examen", "¿Cuándo se presenta el examen?")
    expected = piece("guia", 3, "Examen de admisión: 26 de octubre de 2026.")
    rows = retrieve(q, [expected, piece("guia", 1, "Presentación del examen en la sede elegida.")])
    assert rows[0]["chunk_id"] == expected["chunk_id"]
    assert rows[0]["retrieval_channel"] == "calendar"
