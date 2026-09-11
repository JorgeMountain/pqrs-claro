"""Transporte y guardas reales con SQLite temporal, proveedores dobles y corpus ficticio."""

from copy import deepcopy

from test_draft_service_api import generate, prepared_case
from test_review_service_api import (
    approve,
    assess,
    current,
    save,
    url,
    wait_drafts,
)
from test_review_service_api import review_app as _review_app
from test_source_sufficiency import (
    coverage,
    materialize,
    missing,
    selection,
    source,
)

from pqrs_claro.draft_service import DraftService
from pqrs_claro.review_service import input_hash
from pqrs_claro.source_sufficiency import POLICY_VERSION

review_app = _review_app


def sufficiency(finding):
    support = finding["supports"][0]
    return {
        "policy_version": POLICY_VERSION,
        "coverage_complete": True,
        "coverage": [{
            "aspect": "Requisitos institucionales consultados.",
            "claim": "La norma indica que el comité registra los requisitos institucionales.",
            "use": "rule",
            "citations": [{"chunk_id": support["chunk_id"], "quote": support["quote"]}],
            "explanation": "El pasaje normativo describe expresamente el requisito consultado.",
        }],
        "source_uses": {support["source_id"]: ["rule"]},
        "attribution_only_allowed": True,
        "assessment_kind": "model_coverage_with_literal_checks",
    }


def prepared_with_sufficiency(app, client, *, contradiction=False):
    case, _ = prepared_case(app, count=1)
    run = app.state.library.latest_run(case["id"])
    finding = run["results"][0]
    finding["sufficiency"] = sufficiency(finding)
    if contradiction:
        finding["status"] = "needs_evidence"
        finding["missing"] = [{
            "kind": "fact",
            "description": "Resolver la contradicción entre requisito obligatorio y opcional.",
            "reason_code": "fact_confirmation",
            "basis": "contradiction",
            "affected_claim": "Carácter obligatorio del requisito consultado.",
            "why_unresolved": "Dos pasajes atribuyen condiciones opuestas al mismo requisito.",
            "linked_source_ids": [finding["supports"][0]["source_id"]],
            "linked_chunk_ids": [finding["supports"][0]["chunk_id"]],
        }]
    app.state.library.save_run(run)
    assert generate(client, case).status_code == 202
    draft_run = wait_drafts(app, client, case)
    assert draft_run["status"] in {"ready", "partial"}, draft_run
    response = client.post(url(case, "/start"), json={"version": case["version"]})
    assert response.status_code == 200, response.text
    return case, deepcopy(finding), draft_run["results"][0], response.json()["requests"][0]


def test_draft_result_preserves_sufficiency_without_sharing_mutable_coverage():
    finding = {"supports": [source()]}
    finding["sufficiency"] = sufficiency(finding)
    before = deepcopy(finding["sufficiency"])
    result = DraftService._result(
        {"id": "P1", "label": "1", "title": "Consulta ficticia"},
        finding,
        {"draft": {"status": "needs_review", "paragraphs": [], "pending": []},
         "checks": {"status": "passed", "issues": [], "local_checks": []}},
    )
    assert result["sufficiency"] == before
    result["sufficiency"]["coverage"][0]["citations"][0]["quote"] = "Edición externa"
    assert finding["sufficiency"] == before


def test_complete_finding_reaches_new_review_without_false_pending_or_autoapproval(review_app):
    app, client, engine, _ = review_app
    case, finding, draft, row = prepared_with_sufficiency(app, client)
    expected = finding["sufficiency"]
    assert finding["missing"] == []
    assert draft["sufficiency"] == expected
    assert draft["draft"]["pending"] == []
    assert row["sufficiency"] == expected
    assert row["pending"] == []
    assert row["approval"] is None and row["assessment"] is None
    assert engine.calls == 0
    assert client.get(url(case, "/approved")).status_code == 409
    checked = assess(app, client, case, row)
    assert checked["status"] == "ready", checked
    assert checked["sufficiency"] == expected and checked["approval"] is None
    assert checked["assessment"]["input_hash"] == input_hash(checked)
    assert approve(client, case, checked, confirmed=False).status_code == 422
    approved = approve(client, case, checked)
    assert approved.status_code == 200, approved.text
    snapshot = client.get(url(case, "/approved")).json()["requests"][0]
    assert snapshot["review"]["sufficiency"] == expected
    assert snapshot["approval"]["approved_by"] == "Responsable ficticia"


def test_changed_sufficiency_invalidates_hash_and_sync_preserves_human_text(review_app):
    app, client, engine, _ = review_app
    case, finding, _, row = prepared_with_sufficiency(app, client)
    paragraphs = deepcopy(row["paragraphs"])
    paragraphs[0]["text"] = "Texto ajustado por la revisora ficticia para conservar su alcance."
    edited_response = save(client, case, row, paragraphs=paragraphs)
    assert edited_response.status_code == 200, edited_response.text
    row = edited_response.json()
    approved_response = approve(client, case, assess(app, client, case, row))
    assert approved_response.status_code == 200, approved_response.text
    approved = approved_response.json()
    original_hash = input_hash(approved)
    run = app.state.library.latest_run(case["id"])
    revised = deepcopy(finding["sufficiency"])
    revised["coverage"][0]["explanation"] += " El alcance excluye el cumplimiento particular."
    changed_only_sufficiency = {**approved, "sufficiency": revised}
    assert input_hash(changed_only_sufficiency) != original_hash
    run["results"][0]["sufficiency"] = revised
    app.state.library.save_run(run)
    stale = current(client, case)
    assert stale["stale"] and stale["assessment"] is None and stale["approval"] is None
    assert client.get(url(case, "/approved")).status_code == 409
    synced_response = client.post(url(case, "/start"), json={"version": case["version"]})
    assert synced_response.status_code == 200, synced_response.text
    synced = synced_response.json()["requests"][0]
    assert synced["sufficiency"] == revised
    assert synced["paragraphs"] == approved["paragraphs"]
    assert synced["pending"] == []
    assert not synced["stale"]
    assert synced["assessment"] is None and synced["approval"] is None
    assert synced["revision"] > approved["revision"]
    assert approve(client, case, synced).status_code == 409
    assert engine.calls == 1, "Sincronizar suficiencia no sustituye una evaluación nueva."
    old_snapshot = app.state.reviews.store.approval(approved["approval"]["id"])
    assert old_snapshot["review"]["sufficiency"] == finding["sufficiency"]


def test_contradiction_survives_transport_and_blocks_manual_approval(review_app):
    app, client, _, _ = review_app
    case, finding, draft, row = prepared_with_sufficiency(app, client, contradiction=True)
    assert draft["sufficiency"] == finding["sufficiency"] == row["sufficiency"]
    assert row["sufficiency"]["coverage_complete"] is True
    assert len(row["pending"]) == 1
    pending = row["pending"][0]
    assert pending["description"] == finding["missing"][0]["description"]
    assert pending["stage"] == "evidence" and pending["blocks_approval"] is True
    assert pending["resolution"] is None
    checked = assess(app, client, case, row)
    assert checked["status"] == "needs_evidence", checked
    assert any(check["code"] == "pending_closed" and not check["passed"]
               for check in checked["assessment"]["local_checks"])
    assert approve(client, case, checked).status_code == 409
    assert current(client, case)["approval"] is None


def test_unused_contextual_source_does_not_block_complete_coverage_by_another_source():
    primary = source(document_status="issued", review_status="reviewed")
    context = source(source_id="context-v1", chunk_id="context:1", document_id="context",
                     title="Oficio contextual", filename="contexto.pdf")
    proposed = selection([primary, context], coverage=[coverage(primary)])
    result = materialize(sources=[primary, context], proposed=proposed)
    assert result["status"] == "references_found"
    assert result["missing"] == []
    assert len(result["supports"]) == 2
    preserved = next(item for item in result["supports"] if item["source_id"] == "context-v1")
    assert preserved["document_status"] == "unknown" and preserved["review_status"] == "pending"
    assert "context-v1" not in result["sufficiency"]["source_uses"]
    assert result["warnings"]


def test_concrete_contradiction_in_unused_contextual_source_is_not_metadata_only():
    primary = source(document_status="issued", review_status="reviewed")
    context = source(source_id="context-v1", chunk_id="context:1", document_id="context",
                     title="Oficio contextual", filename="contexto.pdf")
    conflict = missing(
        reason="fact_confirmation", basis="contradiction", source_chunk_ids=["context:1"],
        description="El documento contextual contradice el carácter obligatorio del requisito.",
        affected_claim="Carácter obligatorio del requisito.",
        why_unresolved="Para el mismo periodo, este documento lo describe como opcional.",
    )
    result = materialize(sources=[primary, context], proposed=selection(
        [primary, context], coverage=[coverage(primary)], missing=[conflict],
    ))
    assert result["status"] == "needs_evidence"
    assert any(item["description"] == conflict["description"] for item in result["missing"])
