"""General passage selection on fictional documents."""

from copy import deepcopy

import pytest

from pqrs_claro.source_retrieval import (
    RetrievalIndex,
    _baseline_document_content,
    _calendar_scope_query,
    _date_passages,
    _DocumentPassageRanker,
    _period_concordance,
    _promote_passages,
    _retrieve,
    retrieve,
)


def passage(source, number, text, **changes):
    return {
        "source_id": source, "document_id": source, "chunk_id": f"{source}:{number}",
        "version": 1, "sha256": f"hash-{source}", "title": "Manual de préstamos culturales",
        "filename": "manual.pdf", "category": "institutional_norm", "case_id": None,
        "collection_id": "public", "validity": "current", "page": number,
        "line_start": 1, "line_end": 4, "quote": text, "method": "native",
        "needs_review": False, **changes,
    }


def request(**changes):
    return {
        "id": "Q1", "title": "Datos del préstamo cultural",
        "description": "Qué datos debo comprobar en el comprobante del préstamo cultural",
        "context": {"subject": "Manual de préstamos culturales"},
        "case_id": "new-fictional-case", "allowed_collection_ids": ["public"],
        **changes,
    }


class RankedSemantic:
    def __init__(self, preferred=(), extras=()):
        self.preferred, self.extras, self.calls, self.passage_calls = preferred, extras, [], []

    def rank(self, query, eligible, limit):
        self.calls.append((query, tuple(row["chunk_id"] for row in eligible)))
        return []

    def rank_passages(self, query, eligible, limit):
        self.passage_calls.append((query, tuple(row["chunk_id"] for row in eligible)))
        order = {key: i for i, key in enumerate(self.preferred)}
        rows = sorted(eligible, key=lambda row: order.get(row["chunk_id"], len(order)))
        return [*self.extras, *[{**row, "semantic_score": .9 - i / 100}
                              for i, row in enumerate(rows)]][:limit]


def test_local_fusion_retains_two_lexical_leaders_and_four_passage_budget():
    rows = [passage("policy", n, f"Original literal {n}.") for n in range(1, 9)]
    semantic = RankedSemantic([rows[4]["chunk_id"], rows[5]["chunk_id"]])
    actual = _DocumentPassageRanker("Una consulta nueva", semantic).rank([rows], [rows])[0]
    assert len(actual) == 4
    assert actual[:2] == rows[:2]
    assert rows[4] in actual
    assert all(row in rows for row in actual)
    assert len(semantic.passage_calls) == 1


def test_local_fusion_uses_one_union_and_independent_document_ranks():
    groups = [[passage(source, n, f"Texto original {source} {n}") for n in range(1, 7)]
              for source in ("alpha", "beta", "gamma")]
    preferred = [group[4]["chunk_id"] for group in groups]
    semantic = RankedSemantic(preferred)
    ranked = _DocumentPassageRanker("Datos exigidos", semantic).rank(groups, groups)
    assert len(semantic.passage_calls) == 1
    assert len(semantic.passage_calls[0][1]) == 18
    for group, found in zip(groups, ranked):
        assert len(found) == 4
        assert found[:2] == group[:2]
        assert group[4] in found
        assert {row["source_id"] for row in found} == {group[0]["source_id"]}


@pytest.mark.parametrize("title, answer", [
    ("Lugar de devolución", "El lugar de devolución es la ventanilla central."),
    ("Autorización del traslado", "La autorización del traslado corresponde al comité."),
])
def test_focused_title_recovers_passage_diluted_by_long_description_without_e5(title, answer):
    rows = [passage("policy", n, "Trámite general, formularios, registro y documentación.")
            for n in range(1, 7)]
    rows[4]["quote"] = answer
    query = title + " Informar sobre el trámite, formularios, registro y documentación necesaria."
    result = _DocumentPassageRanker(query, None, title=title).rank([rows], [rows])[0]
    assert len(result) == 4
    assert result[:2] == rows[:2]
    assert rows[4] in result
    assert all(row in rows for row in result)


def test_broad_semantic_similarity_cannot_displace_focused_title_leader():
    rows = [passage("policy", n, "Trámite general, formularios y registro.")
            for n in range(1, 9)]
    rows[4]["quote"] = "El plazo de devolución es de tres días."
    title = "Plazo de devolución"
    semantic = RankedSemantic([row["chunk_id"] for row in reversed(rows)])
    actual = _DocumentPassageRanker(title + " Trámite del registro", semantic,
                                   title=title).rank([rows], [rows])[0]
    assert len(actual) == 4
    assert actual[:2] == rows[:2]
    assert actual[2] == rows[4]


def test_reranker_cannot_inject_revoked_or_stale_citations_or_remove_ocr_control():
    rows = [passage("policy", n, f"Texto vigente {n}") for n in range(1, 7)]
    rows[4].update(method="ocr", needs_review=True)
    forged = {**rows[4], "quote": "Transcripción de una versión anterior", "needs_review": False}
    hidden = passage("private", 20, "Fuera de permisos", collection_id="private")
    semantic = RankedSemantic([rows[4]["chunk_id"]], [hidden, forged])
    actual = _DocumentPassageRanker("Datos", semantic).rank([rows], [rows])[0]
    assert rows[4] in actual
    assert not any(row["source_id"] == "private" for row in actual)
    assert next(row for row in actual if row["chunk_id"] == rows[4]["chunk_id"])["needs_review"]


@pytest.mark.parametrize("raises", [False, True])
def test_failed_or_empty_local_channel_preserves_lexical_results(raises):
    rows = [passage("policy", n, str(n)) for n in range(1, 9)]

    class Unavailable(RankedSemantic):
        def rank_passages(self, query, eligible, limit):
            if raises:
                raise RuntimeError("local model unavailable")
            return []

    result = _DocumentPassageRanker("Consulta", Unavailable()).rank([rows], [rows])
    assert result[0][:4] == rows[:4]


def test_period_match_precedes_closer_event_in_other_period_without_discarding_it():
    q = request(title="Calendario del préstamo", description="Fecha del préstamo cultural 2033-2")
    requested = passage("requested", 2, "La entrega del préstamo cultural será el 18 de junio.",
                        title="Calendario cultural 2033-2")
    previous = passage("previous", 4, "Préstamo cultural 18 de junio.",
                       title="Calendario cultural 2032-2")
    actual = _date_passages(q, [previous, requested], prefer_period=True)
    assert actual == [requested, previous]
    assert _period_concordance(q["description"], requested) == 2
    assert _period_concordance(q["description"], previous) == -1


def test_period_does_not_confuse_signing_year_with_calendar_scope_or_iso_date():
    q = "Calendario del período 2033-2"
    act = passage("act", 1, "Se fija el calendario del período 2033-2.",
                  title="Acto aprobado el 2032-12-11")
    assert _period_concordance(q, act) == 2
    assert _period_concordance(q, passage("iso", 1, "Firma: 2033-02-12")) == 0
    assert _period_concordance("Fecha de la reunión 2034", passage("year", 1, "12/05/2034")) == 1


def test_no_explicit_period_keeps_calendar_order_unchanged():
    q = request(title="Calendario", description="Fecha del préstamo cultural")
    rows = [passage(str(n), 1, f"Préstamo cultural el {n + 1} de junio.",
                    title=f"Calendario {2030 + n}-2") for n in range(4)]
    assert _date_passages(q, rows) == _date_passages(q, rows, prefer_period=True)


def calendar_request_from_original(introduction, question, sibling=None):
    from pqrs_claro.source_context import build_source_requests

    lines = [introduction, question, *([sibling] if sibling else [])]
    questions = [{"id": f"Q{i}", "label": str(i), "title": text,
                  "description": text, "parent_id": None,
                  "source_refs": [{"page": 1, "line_start": i + 1, "line_end": i + 1,
                                   "quote": text}]}
                 for i, text in enumerate(lines[1:], 1)]
    return build_source_requests({
        "id": "fictional-new-calendar",
        "pages": [{"number": 1, "text": "\n".join(lines), "method": "native",
                   "needs_review": False}],
        "identification": {"subject": "Calendario de becas", "requests": questions},
    }, allowed_collection_ids=["public"])[0]


def test_original_shared_period_rescues_a_saturated_calendar_without_inheriting_sibling():
    q = calendar_request_from_original(
        "Consulta sobre las postulaciones a becas de la convocatoria 2039-2.",
        "¿Desde cuándo y hasta cuándo se recibían las postulaciones a becas?",
        "En otro asunto, ¿cuáles son los requisitos de la convocatoria 2040-1?",
    )
    previous = passage("past", 1, "Postulaciones a becas del 3 al 8 de abril.",
                       title="Calendario de becas 2038-2", retrieval_channel="calendar")
    current = passage("current", 1, "Postulaciones a becas del 5 al 12 de abril.",
                      title="Calendario de becas 2039-2", retrieval_channel="calendar")
    unknown = passage("undated", 1, "Información de becas del 6 de abril.",
                      title="Boletín del comité", retrieval_channel="calendar")
    supports = [passage(f"independent-{i}", 1, "Respaldo independiente.",
                        retrieval_channel="semantic") for i in range(22)]
    baseline = [previous, unknown, *supports]
    before = deepcopy(baseline)
    proposals = [{**row, "retrieval_channel": "calendar"} for row in _date_passages(
        q, [previous, current], prefer_period=True)]
    assert proposals[0] == current
    found = _promote_passages(baseline, proposals, limit=24, named_ids=set(),
                             query=_calendar_scope_query(q))
    assert found == [unknown, *supports, current]
    assert baseline == before
    assert "2040-1" not in _calendar_scope_query(q)


@pytest.mark.parametrize("introduction,sibling", [
    ("Consulta de las convocatorias 2039-1 y 2039-2.", None),
    ("Consulta general sobre becas.", "¿Qué cambió en las becas de 2039-2?"),
])
def test_ambiguous_shared_period_or_sibling_only_cannot_replace_a_calendar(introduction, sibling):
    q = calendar_request_from_original(introduction, "¿Cuándo se presentan las becas?", sibling)
    previous = passage("past", 1, "Becas del 3 de abril.", title="Calendario 2038-2",
                       retrieval_channel="calendar")
    proposed = passage("new", 1, "Becas del 5 de abril.", title="Calendario 2039-2",
                       retrieval_channel="calendar")
    atomic = " ".join(q[key] for key in ("title", "description"))
    assert _calendar_scope_query(q) == atomic
    assert _promote_passages([previous], [proposed], limit=1, named_ids=set(),
                             query=_calendar_scope_query(q)) == [previous]


@pytest.mark.parametrize("atomic_period", ["2038-2", "2038"])
def test_atomic_period_or_year_precedes_shared_introduction(atomic_period):
    q = calendar_request_from_original(
        "Consulta general del calendario de becas 2039-2.",
        f"Para comparar, ¿cuándo se presentaban las becas en {atomic_period}?",
    )
    assert _calendar_scope_query(q) == " ".join(q[key] for key in ("title", "description"))
    assert "2039-2" not in _calendar_scope_query(q)


@pytest.mark.parametrize("uncertain", ["truncated", "unverified_request_reference_count"])
def test_incomplete_original_cannot_supply_a_calendar_period(uncertain):
    q = calendar_request_from_original("Consulta de becas 2039-2.", "¿Cuándo se solicitan?")
    q["context"]["document_context"][uncertain] = True
    assert _calendar_scope_query(q) == " ".join(q[key] for key in ("title", "description"))


def test_saturated_results_can_exchange_another_period_but_keep_independent_evidence():
    query = "Fecha de entrega de las becas en 2034-2"
    previous = passage("past", 1, "Entrega de becas el 5 de mayo.",
                       title="Calendario 2034-1", retrieval_channel="calendar")
    undated_scope = passage("uncertain", 1, "Entrega el 4 de mayo.",
                            title="Boletín del comité", retrieval_channel="calendar")
    protected = [passage(f"support-{i}", 1, "Respaldo adicional.",
                         retrieval_channel="semantic") for i in range(22)]
    requested = passage("current", 1, "Entrega de becas el 14 de mayo.",
                        title="Calendario 2034-2", retrieval_channel="calendar")
    baseline = [previous, undated_scope, *protected]
    found = _promote_passages(baseline, [requested], limit=24, named_ids=set(), query=query)
    assert found == [undated_scope, *protected, requested]


@pytest.mark.parametrize(
    "change", ["named", "identity", "ambiguous", "unqualified", "not_calendar"]
)
def test_calendar_rescue_needs_precise_period_and_cannot_displace_protected_support(change):
    query = "Fecha de entrega de las becas en 2034-2"
    previous = passage("past", 1, "La entrega será el 3 de mayo.",
                       title="Calendario 2034-1", retrieval_channel="calendar")
    requested = passage("current", 1, "La entrega será el 15 de mayo.",
                        title="Calendario 2034-2", retrieval_channel="calendar")
    named_ids = {"past"} if change == "named" else set()
    if change == "identity":
        previous["document_identity_rank"] = 1
    if change == "ambiguous":
        previous["title"] = "Circular de entrega"
    if change == "unqualified":
        query = "Fecha de entrega de las becas en 2034"
    if change == "not_calendar":
        requested["retrieval_channel"] = "document_content"
    found = _promote_passages([previous], [requested], limit=1,
                              named_ids=named_ids, query=query)
    assert found == [previous]


def test_regular_retrieve_uses_local_semantics_without_repeating_global_search():
    rows = [passage("guide", n, f"Datos del préstamo cultural. Apartado {n}") for n in range(1, 8)]
    semantic = RankedSemantic([rows[-1]["chunk_id"]])
    before = deepcopy(rows)
    assert retrieve(request(), rows, semantic=semantic)
    assert len(semantic.calls) == 1
    assert len(semantic.passage_calls) == 1
    assert rows == before


def test_candidate_filters_scope_and_superseded_content_before_both_rankings():
    rows = [passage("guide", n, f"Datos del préstamo cultural. Apartado {n}") for n in range(1, 8)]
    excluded = [
        passage("private", 1, "Datos del préstamo cultural", collection_id="secret"),
        passage("old", 1, "Datos del préstamo cultural", validity="superseded"),
        passage("other-case", 1, "Datos del préstamo cultural", case_id="someone-else"),
    ]
    semantic = RankedSemantic([rows[4]["chunk_id"]])
    found = retrieve(request(), [*rows, *excluded], semantic=semantic)
    excluded_ids = {row["chunk_id"] for row in excluded}
    assert semantic.passage_calls
    assert all(not excluded_ids.intersection(ids)
               for _, ids in [*semantic.calls, *semantic.passage_calls])
    assert len(found) <= 24
    assert not excluded_ids.intersection(row["chunk_id"] for row in found)
    assert all({key: row[key] for key in rows[0]} in rows for row in found)


def test_reused_index_cannot_restore_corrected_quote_or_revoked_document():
    rows = [passage("guide", n, f"Datos del préstamo cultural. Apartado {n}") for n in range(1, 8)]
    index = RetrievalIndex(rows)
    q = request()
    assert retrieve(q, rows, index=index, semantic=RankedSemantic())
    corrected = [{**row, "quote": row["quote"] + " Corrección actual.", "version": 2,
                  "sha256": "new-hash"} for row in rows]
    found = retrieve(q, corrected, index=index, semantic=RankedSemantic())
    assert found and all(row["version"] == 2 and row["sha256"] == "new-hash" for row in found)
    assert all(row["quote"].endswith("Corrección actual.") for row in found)
    assert retrieve({**q, "allowed_collection_ids": []}, corrected,
                    index=index, semantic=RankedSemantic()) == []


def test_dense_corpus_preserves_24_budget_and_explicit_document_identity():
    q = request(description="Entregar copia de la Resolución 44 sobre el préstamo cultural")
    policy = [passage("identified", n, f"RESOLUCIÓN 44\nDatos del préstamo cultural. Apartado {n}.",
                      title="Resolución 44", filename="resolucion_44.pdf") for n in range(1, 9)]
    noise = [passage(f"archive-{n}", 1, "Datos del préstamo cultural. Respuesta a la consulta.",
                     title=f"Carta de archivo {n}", category="historical_response")
             for n in range(40)]
    semantic = RankedSemantic([policy[4]["chunk_id"]])
    corpus = [*policy, *noise]
    baseline = _retrieve(q, corpus, semantic=RankedSemantic())
    candidate = retrieve(q, corpus, semantic=semantic)
    assert len(candidate) == 24
    assert len({row["chunk_id"] for row in candidate}) == 24
    identities = {row["chunk_id"] for row in baseline if row.get("document_identity_rank")}
    assert identities
    assert identities.issubset(row["chunk_id"] for row in candidate)
    originals = {row["chunk_id"]: row for row in corpus}
    assert all({key: row[key] for key in originals[row["chunk_id"]]} == originals[row["chunk_id"]]
               for row in candidate)


def test_body_selection_keeps_original_coordinates_under_local_normalization():
    rows = [passage("guide", n, f"Datos del préstamo cultural. Sección {n}.") for n in range(1, 8)]
    q = request()
    ranker = _DocumentPassageRanker(q["title"] + " " + q["description"], RankedSemantic())
    before = deepcopy(rows)
    actual = _baseline_document_content(q, rows, passage_ranker=ranker)
    assert len(actual) == 4
    assert all(row in rows for row in actual)
    assert rows == before
