"""Unseen scopes: balanced channels and literal continuations under a 24-slot budget."""

from copy import deepcopy

import pytest

from pqrs_claro.source_retrieval import (
    RetrievalIndex,
    _document_content,
    _named_scope_sources,
    _retrieve_base,
    retrieve,
)


def passage(source, page, text, *, start=1, **changes):
    return {
        "source_id": source, "document_id": source, "version": 1, "sha256": source,
        "chunk_id": f"{source}:{page}:{start}", "title": "Manual del subsidio rural",
        "filename": "manual.pdf", "category": "institutional_norm", "case_id": None,
        "collection_id": "policies", "validity": "current", "page": page,
        "line_start": start, "line_end": start + len(text.splitlines()) - 1,
        "quote": text, **changes,
    }


def question(**changes):
    return {
        "id": "P1", "title": "Notificación del subsidio",
        "description": "Cómo se comunica el resultado de la solicitud de subsidio rural",
        "context": {"subject": "Información del subsidio rural"},
        "case_id": "new-case", "allowed_collection_ids": ["policies", "archive"],
        **changes,
    }


def historical_noise(size=45):
    return [passage(
        f"old-{n}", 1,
        "Damos respuesta a su solicitud. Notificación del subsidio rural. "
        f"Cómo se comunica el resultado de la solicitud de subsidio rural, trámite {n}.",
        title=f"Archivo de consultas {n}", category="historical_response",
        collection_id="archive",
    ) for n in range(size)]


def test_dense_topic_and_body_matches_cannot_exhaust_semantic_slots():
    q = question()
    bodies = [passage(f"guide-{n // 5}", n % 5 + 1,
                      f"Se comunica el resultado de la solicitud de subsidio rural. Ejemplo {n}.")
              for n in range(15)]
    relevant = [passage(f"meaning-{n}", 20,
                       f"El aviso del beneficio llegará al buzón autorizado. Variante {n}.",
                       title="Instrucciones de comunicación") for n in range(3)]
    topics = [passage(f"topic-{n}", 1, f"Notificación del subsidio. Referencia {n}.",
                     title="Comunicación general") for n in range(6)]
    history = [{**r, "quote": "Damos respuesta a su solicitud. " + q["description"]
                + f". Zona{chr(97+n%26)} grupo{chr(97+n%26)} oficina{chr(97+n%26)}."}
               for n, r in enumerate(historical_noise())]
    hidden = passage("hidden", 1, "Contenido ajeno.", collection_id="not-granted")

    class Semantic:
        calls = 0

        def rank(self, query, eligible, limit):
            self.calls += 1
            assert hidden not in eligible
            return [hidden, *[{**r, "semantic_score": 0.99 - i / 100}
                             for i, r in enumerate(relevant)]]

    semantic = Semantic()
    corpus = [*history, *topics, *bodies, *relevant, hidden]
    before = deepcopy(corpus)
    baseline = _retrieve_base(q, corpus, semantic=Semantic())
    found = retrieve(q, corpus, semantic=semantic)
    assert semantic.calls == 1
    assert len(found) == 24
    assert {r["source_id"] for r in found if r["retrieval_channel"] == "semantic"} == {
        r["source_id"] for r in relevant
    }
    assert "hidden" not in {r["source_id"] for r in found}
    assert corpus == before
    protected = {r["chunk_id"] for r in baseline if r["retrieval_channel"] not in {
        "lexical", "context"}}
    assert protected.issubset({r["chunk_id"] for r in found})
    assert len({r["chunk_id"] for r in baseline} - {r["chunk_id"] for r in found}) <= 4


def test_general_policy_title_needs_scope_match_not_every_article_topic():
    q = question(title="Retiro de personal técnico",
                 description="Qué causas permiten el retiro del personal técnico",
                 context={"subject": "Información sobre retiro y retorno del personal técnico"})
    expected = passage("code", 16, "El retiro se admite por fuerza mayor debidamente acreditada.",
                       title="Reglamento técnico", filename="reglamento.pdf")
    history = passage("history", 4, q["description"], title="Carta antigua",
                      category="historical_response", collection_id="archive")
    rows = _document_content(q, [history, expected])
    assert [r["source_id"] for r in rows] == ["code"]
    assert rows[0]["quote"] == expected["quote"]


def test_original_scope_names_general_policy_under_specific_historical_titles():
    q = question(title="Autoridad para solicitar el retiro",
                 description="Qué autoridad recibe la petición de retiro del personal técnico",
                 context={"subject": "Retiro y retorno de personal técnico"},
                 retrieval_context=(
                     "Consulta del Reglamento técnico, sobre su procedimiento general."))
    expected = passage("code", 16, "La petición de retiro se dirige al Comité Técnico.",
                       title="Reglamento técnico", filename="reglamento.pdf")
    misleading = [passage(f"letter-{i}", 1, q["description"],
                         title=f"Retiro y retorno de personal técnico, historia {i}",
                         category="historical_response", collection_id="archive")
                  for i in range(40)]
    result = retrieve(q, [*misleading, expected])
    assert expected["chunk_id"] in {r["chunk_id"] for r in result}
    assert len(result) <= 24


@pytest.mark.parametrize("next_page,next_start", [(7, 3), (8, 1)])
def test_following_instruction_survives_without_repeating_atomic_terms(next_page, next_start):
    q = question()
    anchor = passage("policy", 7, "Notificación del subsidio rural.\n"
                     "El resultado se enviará al correo registrado.")
    tail = passage("policy", next_page,
                   "Si no aparece el mensaje, revisar las carpetas de filtrado automático.",
                   start=next_start)
    corpus = [*historical_noise(), anchor, tail]
    found = retrieve(q, corpus)
    answer = next(r for r in found if r["chunk_id"] == tail["chunk_id"])
    assert answer["retrieval_channel"] == "source_continuation"
    assert answer["adjacent_to"] == anchor["chunk_id"]
    assert {k: answer[k] for k in tail} == tail
    assert len(found) <= 24


@pytest.mark.parametrize("changes", [
    {"page": 9}, {"line_start": 8}, {"version": 2}, {"sha256": "changed"},
    {"document_id": "different"}, {"source_id": "other"},
    {"collection_id": "not-granted"}, {"case_id": "another"},
    {"validity": "superseded"}, {"category": "archive_only"},
    {"quote": "CAPÍTULO 8. Régimen del personal externo."},
])
def test_continuation_never_bridges_missing_ranges_originals_or_permission_boundaries(changes):
    anchor = passage("policy", 7, "Notificación del subsidio rural.\n"
                     "El resultado se enviará al correo registrado.")
    tail = passage("policy", 7, "Consultar también la carpeta filtrada.", start=3)
    tail.update(changes)
    found = retrieve(question(), [anchor, tail])
    assert not any(r.get("adjacent_to") == anchor["chunk_id"] for r in found)


def test_reused_index_observes_corrected_continuation_and_revoked_permission():
    anchor = passage("policy", 7, "Notificación del subsidio rural.\n"
                     "El resultado se enviará al correo registrado.")
    tail = passage("policy", 7, "Consultar también la carpeta filtrada.", start=3)
    original = [anchor, tail]
    index = RetrievalIndex(original)
    assert tail["chunk_id"] in {r["chunk_id"] for r in retrieve(question(), original, index=index)}
    correction = {**tail, "quote": "Avisar a la oficina si transcurren dos jornadas."}
    found = retrieve(question(), [anchor, correction], index=index)
    current = next(r for r in found if r["chunk_id"] == tail["chunk_id"])
    assert current["quote"] == correction["quote"]
    revoked = {**question(), "allowed_collection_ids": ["archive"]}
    assert retrieve(revoked, [anchor, correction], index=index) == []


def test_semantic_query_keeps_atomic_question_without_long_preamble_with_one_call():
    q = question(retrieval_context=(
        "Programa técnico rural. Consulta informativa, no caso individual."))
    row = passage("policy", 1, "El beneficio tiene una convocatoria anual.")

    class Semantic:
        calls = 0

        def rank(self, query, eligible, limit):
            self.calls += 1
            assert query == q["title"] + " " + q["description"]
            assert q["retrieval_context"] not in query
            return [row]

    semantic = Semantic()
    result = retrieve(q, [row], semantic=semantic, limit=1)
    assert len(result) == semantic.calls == 1
    assert result[0]["quote"] == row["quote"]


def test_literal_scope_name_opens_atomic_body_search_despite_specific_archive_titles():
    q = question(title="Renovación del apoyo rural",
                 description="Qué oficina tramita la renovación del apoyo rural",
                 context={"subject": "Trámite del apoyo rural", "document_context": {
                     "origin": "original_petition", "excerpts": [{"quote":
                         "Consultar el Manual de Ayudas Rurales y el Manual de Ayudas Urbanas."}]}})
    expected = passage("rural", 11, "La renovación del apoyo rural se tramita en Secretaría.",
                       title="Manual de Ayudas Rurales")
    sibling = passage("urban", 12, "El hospital organiza la atención odontológica.",
                      title="Manual de Ayudas Urbanas")
    archive = [passage(f"archive-{i}", 1, q["description"] + f". Variante {i}.",
                       title="Trámite renovación apoyo rural", category="historical_response",
                       collection_id="archive") for i in range(12)]
    rows = _document_content(q, [*archive, sibling, expected])
    assert expected["chunk_id"] in {r["chunk_id"] for r in rows}
    assert sibling["chunk_id"] not in {r["chunk_id"] for r in rows}
    assert next(r for r in rows if r["source_id"] == "rural")["quote"] == expected["quote"]


def test_atomic_document_name_precedes_other_scope_document_without_transferring_criteria():
    q = question(title="Manual de Ayudas Urbanas",
                 description="Cómo se renueva el apoyo según el Manual de Ayudas Urbanas",
                 context={"document_context": {"origin": "original_petition", "excerpts": [
                     {"quote": "Otro numeral consulta el Manual de Ayudas Rurales."}]}})
    rural = passage("rural", 11, "La renovación requiere una visita a la finca.",
                    title="Manual de Ayudas Rurales")
    urban = passage("urban", 12, "La renovación se presenta en la oficina municipal.",
                    title="Manual de Ayudas Urbanas")
    assert _named_scope_sources(q, [rural, urban]) == {"urban"}


def test_original_signature_does_not_create_context_channel_candidates():
    q = question(retrieval_context="Gracias por su atención. Solicitante 2099.",
                 retrieval_queries=["Gracias por su atención. Solicitante 2099."],
                 context={"subject": "Apoyo rural", "document_context": {
                     "origin": "original_petition", "excerpts": []}})
    signature = passage("footer", 1, q["retrieval_context"], title="Saludos de archivo")
    answer = passage("guide", 2, "El resultado del subsidio rural se comunica por carta.")
    found = retrieve(q, [signature, answer])
    assert signature["chunk_id"] not in {r["chunk_id"] for r in found}


def test_letterhead_number_is_not_a_document_reference_but_atomic_number_is_preserved():
    unrelated = passage("act", 1, "El apoyo rural se notifica por escrito.",
                        title="Resolución 2099", filename="resolucion_2099.pdf")
    guide = passage("guide", 2, "El apoyo rural se notifica por correo.",
                    title="Manual del apoyo rural")
    q = question(title="Notificación del apoyo rural",
                 description="Cómo se notifica el apoyo rural",
                 context={"subject": "Información del apoyo rural"},
                 retrieval_context="Identificador personal 2099. Fecha 15 de julio.")
    rows = _document_content(q, [unrelated, guide])
    assert {r["source_id"] for r in rows} == {"guide"}
    explicit = {**q, "description": "Qué indica la Resolución 2099 sobre el apoyo rural"}
    assert "act" in {r["source_id"] for r in _document_content(explicit, [unrelated, guide])}


def test_short_policy_name_inside_issuing_act_opens_its_body_not_other_staff_policy():
    q = question(title="Composición del comité",
                 description="Quién forma el comité evaluador",
                 context={"subject": "Evaluación del personal", "document_context": {
                     "origin": "original_petition", "excerpts": [{"quote":
                         "Solicito información del Estatuto Investigador."}]}})
    correct = passage("research", 20, "El comité evaluador tiene tres representantes elegidos.",
                       title="Ordenanza 42 por la cual se expide el Estatuto Investigador")
    other = passage("admin", 19, "El comité evaluador lo designa la jefatura administrativa.",
                     title="Ordenanza 19 por la cual se expide el Estatuto Administrativo")
    assert _named_scope_sources(q, [other, correct]) == {"research"}
    assert correct["chunk_id"] in {r["chunk_id"] for r in _document_content(q, [other, correct])}
    explicit = {**q, "description": "Quién forma el comité según el Estatuto Administrativo"}
    assert _named_scope_sources(explicit, [other, correct]) == {"admin"}


def test_generic_policy_name_alone_does_not_link_an_arbitrary_sibling_document():
    q = question(retrieval_context="Consultar el Reglamento General y el Acuerdo Superior.")
    generic = passage("generic", 1, "Las reglas de organización son públicas.",
                      title="Acuerdo Superior sobre el Reglamento General")
    assert _named_scope_sources(q, [generic]) == set()


def test_previous_page_condition_is_retained_as_an_independent_original_quote():
    q = question(title="Retorno a la actividad", description="Quién tramita el retorno",
                 context={"subject": "Estatuto Investigador", "document_context": {
                     "origin": "original_petition", "excerpts": [
                         {"quote": "Consulta del Estatuto Investigador."}]}})
    condition = passage("policy", 11, "La condición anterior excluye al personal provisional.",
                        title="Estatuto Investigador")
    anchor = passage("policy", 12, "El retorno se tramita ante la coordinación académica.",
                     title="Estatuto Investigador")
    result = retrieve(q, [*historical_noise(), condition, anchor])
    previous = next(row for row in result if row["chunk_id"] == condition["chunk_id"])
    assert previous["adjacent_to"] == anchor["chunk_id"]
    assert {key: previous[key] for key in condition} == condition


def test_body_anchor_precedes_earlier_topic_hit_for_same_document_continuation():
    q = question()
    before = passage("policy", 1, "Portada administrativa del programa.")
    topic = passage("policy", 2, "Notificación del subsidio. Glosario y presentación.")
    middle = passage("policy", 3, "La identificación se presenta en ventanilla.")
    anchor = passage("policy", 4,
                     "El resultado de la solicitud de subsidio rural se comunica al correo.\n"
                     "El medio electrónico es el canal autorizado.")
    tail = passage("policy", 4, "Si faltara, revisar las carpetas segregadas.", start=3)
    rows = retrieve(q, [*historical_noise(), before, topic, middle, anchor, tail])
    found = next(row for row in rows if row["chunk_id"] == tail["chunk_id"])
    assert found["adjacent_to"] == anchor["chunk_id"]
    assert found["retrieval_channel"] == "source_continuation"
    assert len(rows) <= 24


def test_separated_policy_kind_and_shared_scope_exclude_sibling_scope():
    q = question(title="Revisión de la evaluación", description="Quién decide el recurso",
                 context={"subject": "Evaluación del personal", "document_context": {
                     "origin": "original_petition", "excerpts": [{"page": 1, "line_start": 1,
                         "line_end": 3, "quote": "Mi consulta es del personal investigador.\n"
                         "Solicito conocer el trámite del reglamento.\n"
                         "Otra pregunta consulta al personal administrativo."}],
                     "question_ranges": [{"request_id": "sibling", "page": 1,
                                          "line_start": 3, "line_end": 3}]}})
    researcher = passage("research", 20, "La dirección decide el recurso.",
                          title="Reglamento Investigador")
    administrator = passage("admin", 19, "El recurso se dirige a la oficina administrativa.",
                             title="Reglamento Administrativo")
    assert _named_scope_sources(q, [researcher, administrator]) == {"research"}
    explicit = {**q, "description": "Quién decide el recurso del personal administrativo"}
    assert _named_scope_sources(explicit, [researcher, administrator]) == {"admin"}
    q["context"]["document_context"]["excerpts"][0]["quote"] = (
        "Solicito conocer las reglas generales.\nEl procedimiento debe quedar claro.\n"
        "Otra pregunta consulta al personal administrativo.")
    assert _named_scope_sources(q, [researcher, administrator]) == set()


def test_literal_list_continuation_precedes_generic_neighbours_under_four_slot_cap():
    q = question(title="Criterios de reconocimiento",
                 description="Qué criterios se usan para reconocer módulos",
                 context={"subject": "Reconocimiento modular"})
    guides = []
    for i in range(5):
        guides.extend([
            passage(f"guide-{i}", 1,
                    f"Criterios de reconocimiento. Se homologan módulos en la guía {i}.",
                    title="Guía de reconocimiento modular"),
            passage(f"guide-{i}", 2, "Una condición anexa de organización interna.",
                    title="Guía de reconocimiento modular"),
        ])
    history = [{**row, "quote": "Damos respuesta a su solicitud. " + q["description"]
                + f". Zona{chr(97+i%26)} grupo{chr(97+i%26)} oficina{chr(97+i%26)}."}
               for i, row in enumerate(historical_noise())]
    anchor = passage("policy", 9,
                     "Para reconocer módulos se exigen estas condiciones:\n"
                     "- Estar acreditado.\n- Homologar la carga.\n9", title="Reglamento local")
    tail = passage("policy", 10,
                   "Reglamento local\n- Contenido pertinente y actual.\n"
                   "Las escalas se convierten mediante una tabla oficial.",
                   title="Reglamento local")

    class Semantic:
        def rank(self, query, eligible, limit):
            return [anchor]

    rows = retrieve(q, [*history, *guides, anchor, tail], semantic=Semantic())
    found = next(row for row in rows if row["chunk_id"] == tail["chunk_id"])
    assert found["adjacent_to"] == anchor["chunk_id"]
    assert {key: found[key] for key in tail} == tail
    assert len(rows) <= 24
