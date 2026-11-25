import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver
from test_source_uncertainties import fixture as conflicting_regulations

from pqrs_claro import config
from pqrs_claro.draft_engine import _candidate_inventory
from pqrs_claro.draft_service import DraftService
from pqrs_claro.evidence_contract import apply_evidence_contract
from pqrs_claro.independent_support import assess_with_independent_support
from pqrs_claro.models import DomainError
from pqrs_claro.review_service import ReviewService
from pqrs_claro.source_assessment import OpenAISourceAssessor, _SourceSelection
from pqrs_claro.source_graph import build_source_graph


def example():
    text = "¿Qué fechas indicaba el calendario de admisión 2027-1 para presentar el examen?"
    request = {
        "id": "P2",
        "description": text,
        "case_id": "test",
        "allowed_collection_ids": ["historical"],
        "request_requirements": [{"id": "R1", "text": text}],
    }
    quote = "El examen de admisión se efectuará el 26 y el 27 de octubre de 2026."
    native = {
        "source_id": "guia",
        "document_id": "guia",
        "chunk_id": "guia:44:5:6",
        "quote": quote,
        "title": "Guía 2027-1",
        "filename": "guia.pdf",
        "page": 44,
        "line_start": 5,
        "line_end": 6,
        "version": 1,
        "sha256": "a" * 64,
        "extraction_revision": 1,
        "category": "institutional_norm",
        "method": "native",
        "review_status": "reviewed",
        "validity": "current",
        "is_latest": True,
        "needs_review": False,
        "extraction_status": "partial",
        "location_kind": "page",
    }
    ocr = {
        **native,
        "chunk_id": "cal:1:2:3",
        "source_id": "cal",
        "document_id": "cal",
        "title": "Calendario aprobado",
        "filename": "cal.pdf",
        "page": 1,
        "category": "historical_attachment",
        "collection_id": "historical",
        "sha256": "b" * 64,
        "needs_review": True,
        "method": "ocr",
        "validity": "not_applicable",
    }
    return request, [ocr, native]


def assessed(request, candidates, claim="El examen se realizaría el 26 y 27 de octubre de 2026.",
             *, selected=None):
    chosen = candidates if selected is None else selected
    selection = _SourceSelection.model_validate(
        {
            "status": "references_found",
            "summary": claim,
            "warnings": [],
            "missing": [],
            "supports": [
                {
                    "chunk_id": c["chunk_id"],
                    "reason": claim,
                    "role": ("fact" if c["category"] == "case_evidence" else "rule")
                    if c["method"] == "native" else "historical_evidence",
                }
                for c in chosen
            ],
            "coverage_complete": True,
            "coverage": [
                {
                    "aspect": request["description"],
                    "claim": claim,
                    "use": "attributed_content",
                    "explanation": "La información consta en el pasaje.",
                    "citations": [
                        {"chunk_id": c["chunk_id"], "quote": c["quote"]} for c in chosen
                    ],
                    "application": {
                        "status": "not_requested",
                        "uncertainty_indexes": [],
                        "explanation": "Se pregunta por el contenido del calendario.",
                    },
                }
            ],
            "requirement_checks": [
                {
                    "requirement_id": "R1",
                    "status": "supported",
                    "coverage_indexes": [0],
                    "missing_indexes": [],
                    "explanation": "El pasaje contiene la información solicitada.",
                }
            ],
        }
    )
    return OpenAISourceAssessor._materialize(selection, request, candidates)


def test_separate_native_reading_keeps_open_ocr_outside_the_draft():
    req, candidates = example()
    calls, scope_checks = [], []

    def read(request, rows):
        calls.append([r["source_id"] for r in rows])
        return assessed(request, rows)

    result = assess_with_independent_support(
        req, candidates, read, check_scope=lambda: scope_checks.append(1)
    )
    assert calls == [["cal", "guia"], ["guia"]] and len(scope_checks) == 2
    result = apply_evidence_contract(req, result)
    assert result["status"] == "references_found" and result["missing"] == []
    assert [s["source_id"] for s in result["supports"]] == ["guia"]
    assert result["sufficiency"]["coverage"][0]["citations"] == [
        {"chunk_id": candidates[1]["chunk_id"], "quote": candidates[1]["quote"]}
    ]
    [check] = result["secondary_source_checks"]
    assert check["linked_source_ids"] == ["cal"] and check["resolution"]["status"] == "open"
    assert not check["blocks_approval"]
    chunks = {r["chunk_id"]: r for r in candidates}
    choices = ReviewService._supports(req, result, chunks)
    assert [c["source_id"] for c in choices] == ["guia"]
    old_groups = [{"chunks": doc["chunks"]} for doc in result["candidate_documents"]]
    old_finding = {**result, "candidate_documents": old_groups}
    assert ReviewService._supports(req, old_finding, chunks) == choices
    assert [d["source_id"] for d in _candidate_inventory(result)] == ["guia"]
    assert not any("transcripción" in warning for warning in result["warnings"])
    row = {"pending": ReviewService._pending([], result, request=req)}
    assert DraftService._ready_for_draft(row, result)
    assert "approval" not in row


def test_graph_checks_case_scope_before_a_second_read():
    req, candidates = example()
    reads = []

    def read(request, rows):
        reads.append(len(rows))
        return assessed(request, rows)

    def check_scope():
        if reads:
            raise DomainError("Vínculo retirado")

    graph = build_source_graph(
        lambda request, chunks: chunks, SimpleNamespace(assess=read),
        MemorySaver(), check_scope=check_scope,
    )
    with pytest.raises(DomainError, match="Vínculo retirado"):
        graph.invoke({"request": req, "chunks": candidates},
                     {"configurable": {"thread_id": "test-revocation"}})
    assert reads == [2]


def test_disabling_conditional_read_restores_one_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.delenv("PQRS_CLARO_INDEPENDENT_OCR_READ", raising=False)
    assert config.Settings.load().independent_ocr_read
    monkeypatch.setenv("PQRS_CLARO_INDEPENDENT_OCR_READ", "0")
    settings = config.Settings.load()
    req, candidates = example()
    calls = []

    def read(request, rows):
        calls.append(len(rows))
        return assessed(request, rows)

    graph = build_source_graph(lambda request, chunks: chunks, SimpleNamespace(assess=read),
                               MemorySaver(), independent_ocr_read=settings.independent_ocr_read)
    state = graph.invoke({"request": req, "chunks": candidates},
                         {"configurable": {"thread_id": "classic-ocr"}})
    assert calls == [2] and state["finding"]["status"] == "needs_evidence"
    assert not state["finding"].get("secondary_source_checks")
    monkeypatch.setenv("PQRS_CLARO_INDEPENDENT_OCR_READ", "typo")
    with pytest.raises(ValueError, match="PQRS_CLARO_INDEPENDENT_OCR_READ"):
        config.Settings.load()


@pytest.mark.parametrize(
    "reason",
    [
        "contradiction",
        "different_date",
        "event",
        "actor",
        "rescheduled",
        "negation",
        "provider_error",
        "incomplete",
        "revoked",
        "duplicate_original",
        "invented_quote",
        "wrong_page",
        "named_authority",
        "unreviewed",
        "certification",
        "error_on_primary",
    ],
)
def test_incomplete_or_conflicting_evidence_preserves_ocr_gate(reason):
    req, candidates = example()
    primary = assessed(req, candidates)
    alternate = assessed(req, candidates[1:])
    if reason == "contradiction":
        primary["missing"][0]["basis"] = "contradiction"
    elif reason == "different_date":
        alternate["sufficiency"]["coverage"][0]["claim"] = "26 y 27 de noviembre de 2026."
    elif reason in {"event", "actor", "rescheduled", "negation"}:
        wording = {
            "event": "La inscripción se realizaría",
            "actor": "El examen de otra sede se realizaría",
            "rescheduled": "El examen se reprogramó para",
            "negation": "El examen no se realizaría",
        }
        alternate["sufficiency"]["coverage"][0]["claim"] = (
            wording[reason] + " el 26 y 27 de octubre de 2026."
        )
    elif reason == "incomplete":
        alternate["sufficiency"]["requirement_checks"] = []
    elif reason == "revoked":
        candidates[1]["collection_id"] = "restricted"
    elif reason == "duplicate_original":
        candidates[1]["sha256"] = candidates[0]["sha256"]
    elif reason == "invented_quote":
        alternate["sufficiency"]["coverage"][0]["citations"][0]["quote"] = "La sede era otra."
    elif reason == "wrong_page":
        alternate["supports"][0]["page"] += 1
    elif reason == "named_authority":
        req["description"] = "¿Qué fecha figuraba en la Resolución 15?"
    elif reason == "unreviewed":
        candidates[1]["review_status"] = "pending"
    elif reason == "certification":
        req["description"] = "Solicito certificación de la fecha del examen."
    elif reason == "error_on_primary":
        primary["status"] = "error"

    calls = []

    def read(request, rows):
        calls.append(len(rows))
        if len(calls) == 1:
            return deepcopy(primary)
        if reason == "provider_error":
            raise DomainError("Proveedor temporalmente indisponible.")
        return alternate

    result = assess_with_independent_support(req, candidates, read)
    assert calls == (
        [2, 1]
        if reason
        in {
            "different_date",
            "event",
            "actor",
            "rescheduled",
            "negation",
            "incomplete",
            "provider_error",
            "invented_quote",
            "wrong_page",
        }
        else [2]
    )
    assert result["missing"] == primary["missing"]
    assert not result.get("secondary_source_checks")
    row = {"pending": ReviewService._pending([], result, request=req)}
    assert not DraftService._ready_for_draft(row, result)


@pytest.mark.parametrize(("field", "original"), [
    ("source_refs", "Por favor expida una certificación de las fechas del examen."),
    ("source_refs", "Indique los días del examen y que emita una certificación."),
    ("request_requirements", "Expida una certificación con las fechas del examen."),
    ("source_refs", "Según el Calendário aprobado que adjunto, ¿qué días indica para el examen?"),
    ("description", "Indique qué fechas consignaba el archivo CAL.PDF para el examen."),
])
def test_original_mandate_or_named_transcription_preserves_control(field, original):
    req, candidates = example()
    if field == "source_refs":
        req[field] = [{"quote": original}]
    elif field == "request_requirements":
        req[field][0]["text"] = original
    else:
        req[field] = original
    calls = []

    def read(request, rows):
        calls.append(len(rows))
        return assessed(request, rows)

    result = assess_with_independent_support(req, candidates, read)
    assert calls == [2] and result["status"] == "needs_evidence"
    assert not result.get("secondary_source_checks") and result["missing"][0]["blocks_approval"]


@pytest.mark.parametrize(("reference", "expected_calls"), [
    ("De acuerdo con el calendario de admisión 2027-1", [2, 1]),
    ("De acuerdo con el Acuerdo 446", [2]),
    ("De acuerdo con el Acuerdo Superior", [2]),
])
def test_de_acuerdo_con_only_preserves_gate_for_a_named_authority(reference, expected_calls):
    req, candidates = example()
    req["description"] = f"{reference}, ¿qué fechas se indicaban para presentar el examen?"
    calls = []

    def read(request, rows):
        calls.append(len(rows))
        return assessed(request, rows)

    result = assess_with_independent_support(req, candidates, read)
    assert calls == expected_calls
    assert result["status"] == ("needs_evidence" if len(calls) == 1 else "references_found")


@pytest.mark.parametrize(("question", "claim", "category"), [
    ("¿Cuántos libros permite retirar el préstamo externo?",
     "El reglamento permite retirar tres libros simultáneamente.", "institutional_norm"),
    ("¿Por qué canal se reciben solicitudes de tutoría?",
     "Las solicitudes de tutoría se reciben mediante el portal de la facultad.", "case_evidence"),
])
def test_native_candidate_not_chosen_on_first_read_can_support_answer(question, claim, category):
    request, candidates = example()
    request["id"] = "consulta"
    request["description"] = request["request_requirements"][0]["text"] = question
    ocr, native = candidates
    ocr.update(title="Anexo escaneado", filename="anexo.pdf", quote=claim)
    native.update(
        title="Condiciones del servicio", filename="servicio.pdf", quote=claim,
        category=category,
        case_id=request["case_id"] if category == "case_evidence" else None,
    )
    distractor = {**native, "source_id": "otro", "document_id": "otro", "sha256": "f"*64,
                  "chunk_id": "otro:2:1:5", "quote": "Requisitos para ingreso a posgrados."}
    calls = []

    def read(current, rows):
        calls.append([r["chunk_id"] for r in rows])
        if len(calls) == 1:
            # The OCR-only finding is valid, but carries a mandatory transcription check.
            return assessed(current, rows, claim, selected=[ocr])
        assert current["_claims_to_verify"] == [
            {"requirement_id": "R1", "claims": [{"claim": claim, "use": "attributed_content"}]}
        ]
        assert "_claims_to_verify" not in request
        assert {r["chunk_id"] for r in rows} == {native["chunk_id"], distractor["chunk_id"]}
        return assessed(current, rows, claim, selected=[native])

    result = assess_with_independent_support(request, [ocr, distractor, native], read)
    assert len(calls) == 2
    assert result["status"] == "references_found" and not result["missing"]
    assert [s["source_id"] for s in result["supports"]] == [native["source_id"]]
    assert result["secondary_source_checks"][0]["linked_source_ids"] == [ocr["source_id"]]
    assert result["sufficiency"]["coverage"][0]["citations"] == [
        {"chunk_id": native["chunk_id"], "quote": claim}
    ]


def test_native_candidate_conflicting_with_ocr_amount_does_not_clear_control():
    request, (scan, native) = example()
    request["description"] = request["request_requirements"][0]["text"] = "¿Cuál es la tarifa?"
    scan["quote"] = "La tarifa por persona es de 120,50 pesos."
    native["quote"] = "La tarifa por persona es de 120,05 pesos."
    def read(current, rows):
        source = native if "_claims_to_verify" in current else scan
        return assessed(current, [source], source["quote"])
    result = assess_with_independent_support(request, [scan, native], read)
    assert result["independent_read_status"] == "insufficient"
    assert result["missing"][0]["blocks_approval"]


def test_partial_independent_coverage_keeps_ocr_for_compound_question():
    request, (scan, native) = example()
    question = "¿Cuál es el plazo y cuál es el canal para pedir una tutoría?"
    request["description"] = question
    request["request_requirements"][0]["text"] = "Indicar el plazo."
    missing_unit = {"id": "R2", "text": "Indicar el canal."}
    scan["quote"] = "La solicitud se presenta en el portal, con dos días de anticipación."
    native["quote"] = "Las solicitudes deben presentarse con dos días de anticipación."
    claim = "El plazo es de dos días de anticipación."
    primary = assessed(request, [scan, native], claim, selected=[scan])
    secondary = assessed(request, [native], claim)
    request["request_requirements"] = [*request["request_requirements"], missing_unit]
    proof = primary["sufficiency"]
    proof["request_requirements"] = request["request_requirements"]
    proof["coverage"].append(
        {**deepcopy(proof["coverage"][0]), "claim": "Se solicita en el portal."}
    )
    proof["requirement_checks"].append({**deepcopy(proof["requirement_checks"][0]),
                                        "requirement_id": "R2", "coverage_indexes": [1]})
    reads = []

    def read(current, rows):
        reads.append(len(rows))
        if len(reads) == 1:
            return primary
        assert len(current["_claims_to_verify"]) == 2
        return secondary

    result = assess_with_independent_support(request, [scan, native], read)
    assert reads == [2, 1]
    assert result["independent_read_status"] == "insufficient"
    assert result["missing"] == primary["missing"]


def test_source_reader_receives_hypotheses_separate_from_citable_passages():
    request, (_, native) = example()
    hypotheses = [{"requirement_id": "R1", "claims": [
        {"claim": "Enunciado provisional para comprobar.", "use": "attributed_content"}
    ]}]
    calls = []

    def parse(**args):
        calls.append(args)
        return SimpleNamespace(status="incomplete", output_parsed=None)

    reader = OpenAISourceAssessor("test-not-real", "test-model")
    reader.client.close()
    reader.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    for current in [request, {**request, "_claims_to_verify": hypotheses}]:
        with pytest.raises(DomainError, match="no terminó"):
            reader.assess(current, [native])
    initial, alternate = [json.loads(call["input"]) for call in calls]
    assert "hypotheses_to_verify" not in initial
    assert alternate["hypotheses_to_verify"] == hypotheses
    assert alternate["request"] == initial["request"]
    assert "_claims_to_verify" not in alternate["request"]
    assert alternate["candidates"] == initial["candidates"]
    assert "confirmar o refutar" in calls[1]["instructions"]
    assert "fórmula genérica" in calls[1]["instructions"]


@pytest.mark.parametrize(
    "alternate_claim",
    [
        "Según la Guía técnica para aspirantes nuevos 2027-1 - V4, el examen de admisión "
        "se efectuará el 26 y el 27 de octubre de 2026.",
        "La Guía técnica para aspirantes nuevos 2027-1 - V4 señala que el examen de admisión "
        "se efectuará el 26 y el 27 de octubre de 2026.",
        "La Guía técnica para aspirantes nuevos 2027-1 establece que el examen de admisión "
        "se efectuaría el 26 y 27 de octubre de 2026.",
        "El calendario de admisión para el período 2027-1 consignaba el examen de admisión "
        "para el 26 y 27 de octubre de 2026.",
        "Para la convocatoria 2027-1, el examen de admisión se efectuará el 26 y el 27 "
        "de octubre de 2026.",
        "El examen de admisión de la convocatoria 2027-1 se presentará en los días 26 y 27 "
        "de octubre de 2026.",
        "El examen de admisión para el periodo 2027-1 estaba programado para los días "
        "26 y 27 de octubre de 2026.",
    ],
)
def test_harmless_attribution_and_period_paraphrases_pass_independent_read(alternate_claim):
    request, (scan, native) = example()
    native["title"] = "Guía técnica para aspirantes nuevos 2027-1 - V4"
    primary_claim = (
        "El calendario de admisión para 2027-1 establecía el examen "
        "para los días 26 y 27 de octubre de 2026."
    )
    primary = assessed(request, [scan, native], primary_claim)
    secondary = assessed(request, [native], alternate_claim)

    def read(current, rows):
        return secondary if "_claims_to_verify" in current else primary

    result = assess_with_independent_support(request, [scan, native], read)
    assert result["independent_read_status"] == "supported"
    assert result["status"] == "references_found" and not result["missing"]
    assert [s["source_id"] for s in result["supports"]] == [native["source_id"]]
    assert result["secondary_source_checks"][0]["blocks_approval"] is False


@pytest.mark.parametrize(
    ("alternate_title", "alternate_claim"),
    [
        (
            "Guía técnica para aspirantes nuevos 2026-2 - V4",
            "Según la Guía técnica para aspirantes nuevos 2026-2 - V4, el examen de admisión "
            "se efectuará el 26 y el 27 de octubre de 2026.",
        ),
        (
            "Guía técnica para aspirantes nuevos 2027-1 - V4",
            "Para la convocatoria 2026-2, el examen de admisión se efectuará el 26 y el 27 "
            "de octubre de 2026.",
        ),
        (
            "Guía técnica para aspirantes nuevos 2027-1 - V4",
            "El examen de admisión se efectuará el 26 y el 27 de octubre de 2026.",
        ),
        (
            "Guía técnica para aspirantes nuevos 2027-1 - V4",
            "Para la convocatoria 2027-1, el examen de admisión se realizó el 26 y el 27 "
            "de octubre de 2026.",
        ),
        (
            "Guía técnica para aspirantes nuevos 2027-1 - V4",
            "El Consejo Académico dispuso que para 2027-1 el examen de admisión se efectuará "
            "el 26 y el 27 de octubre de 2026.",
        ),
        (
            "Guía técnica para aspirantes nuevos 2027-1 - V4",
            "Para la convocatoria 2027-1, el examen de admisión virtual se efectuará el 26 y "
            "el 27 de octubre de 2026.",
        ),
    ],
)
def test_period_authority_tense_or_condition_changes_still_keep_ocr_gate(
    alternate_title, alternate_claim
):
    request, (scan, native) = example()
    native["title"] = alternate_title
    primary_claim = (
        "El calendario de admisión para 2027-1 establecía el examen "
        "para los días 26 y 27 de octubre de 2026."
    )
    primary = assessed(request, [scan, native], primary_claim)
    secondary = assessed(request, [native], alternate_claim)

    def read(current, rows):
        return secondary if "_claims_to_verify" in current else primary

    result = assess_with_independent_support(request, [scan, native], read)
    assert result["independent_read_status"] == "insufficient"
    assert result["missing"] == primary["missing"]
    assert not result.get("secondary_source_checks")


def test_swapped_multi_period_claims_do_not_match():
    request, (scan, native) = example()
    primary = assessed(
        request,
        [scan, native],
        "Los admitidos de 2026-2 pueden reservar cupo para 2027-1.",
    )
    secondary = assessed(
        request,
        [native],
        "Los admitidos de 2027-1 pueden reservar cupo para 2026-2.",
    )

    def read(current, rows):
        return secondary if "_claims_to_verify" in current else primary

    result = assess_with_independent_support(request, [scan, native], read)
    assert result["independent_read_status"] == "insufficient"
    assert result["missing"] == primary["missing"]


def test_conflicting_native_sources_remain_auditable_with_separate_ocr_control():
    request, (scan, _) = example()
    _, native, selection = conflicting_regulations()
    for source in native:
        source["method"] = "native"
    question = "¿Cuántas horas dura la reserva de la sala?"
    request["description"] = request["request_requirements"][0]["text"] = question
    scan["quote"] = native[0]["quote"]
    claim = "La reserva caduca a las seis horas."
    primary = assessed(request, [scan, *native], claim, selected=[scan])
    secondary = OpenAISourceAssessor._materialize(
        _SourceSelection.model_validate(selection), request, native)

    def read(current, rows):
        if "_claims_to_verify" in current:
            assert rows == native
            return secondary
        return primary

    result = assess_with_independent_support(request, [scan, *native], read)
    assert result["missing"] == primary["missing"] and result["checks"] == primary["checks"]
    assert result["supports"] == primary["supports"]
    assert "secondary_source_checks" not in result
    conflict, = result["independent_read_conflicts"]
    assert conflict["requirement_ids"] == ["R1"] and conflict["reason"]
    assert [(c["source_id"], c["quote"]) for c in conflict["citations"]] == [
        (s["source_id"], s["quote"]) for s in native
    ]
