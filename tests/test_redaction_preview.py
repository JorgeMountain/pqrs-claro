"""Selected Redacción must retain the same citation identity and enforce current access."""
# ruff: noqa: F811 (pytest fixtures imported from the review and scope regression suites)

from test_draft_service_api import generate, prepared_case, ready_map, wait_drafts
from test_review_service_api import prepare, review_app, url  # noqa: F401
from test_source_scope_revocation import (
    COLLECTION,
    PENDING,
    QUOTE,
    TITLE,
    env,  # noqa: F401
    start_search,
    wait_search,
)


def test_select_second_request_and_replace_original(review_app):
    app, client, _, _ = review_app
    pending = [{"kind": "fact", "description": "Confirmar el plazo del trámite."}]
    case, source, _ = prepare(app, client, count=3, pending=pending)
    endpoint = url(case, "/requests/P2/preview")
    preview = client.get(endpoint)
    assert preview.status_code == 200 and preview.headers["Cache-Control"] == "no-store"
    saved = client.get(url(case)).json()["requests"][1]
    full = client.get(f"/api/cases/{case['id']}/sources?compact=true").json()["results"][1]
    chosen = preview.json()
    assert chosen["request_id"] == "P2"
    assert chosen["review"]["requests"] == [saved]
    assert "reading_confirmation" not in chosen["review"]
    assert len(chosen["mapping"]["results"]) == 1
    finding = chosen["mapping"]["results"][0]
    assert finding["request_id"] == "P2" and finding["supports"] == full["supports"]
    assert finding["missing"] == full["missing"]
    assert client.get(url(case, "/requests/absent/preview")).status_code == 404
    old = finding["supports"][0]["quote"]
    replacement = "Texto corregido para el expediente ficticio."
    new_version = app.state.library.add(
        "norma.txt", replacement.encode(), title=source["title"], category=source["category"],
        origin="Prueba", document_id=source["document_id"])
    changed = client.get(endpoint)
    assert changed.json()["mapping"]["stale"] and not changed.json()["mapping"]["results"]
    assert old not in changed.text and pending[0]["description"] not in changed.text
    ready_map(app, case)
    refreshed = client.get(endpoint)
    support = refreshed.json()["mapping"]["results"][0]["supports"][0]
    assert (support["source_id"], support["version"], support["quote"]) == (
        new_version["id"], new_version["version"], replacement)
    assert refreshed.json()["mapping"]["results"][0]["missing"] == []
    assert old not in refreshed.text and pending[0]["description"] not in refreshed.text


def test_selected_preview_unlink_before_new_search(env):
    app, client, case, restricted, _, path, _ = env
    endpoint = path + "/review/requests/P1/preview"
    start_search(client, case)
    wait_search(app, client, case["id"])
    assert QUOTE in client.get(endpoint).text
    assert client.put(path + "/source-collections", json={"collection_ids": []}).status_code == 200
    withdrawn = client.get(endpoint)
    assert withdrawn.json()["mapping"]["scope_revoked"]
    for text in (QUOTE, TITLE, COLLECTION, restricted["id"]):
        assert text not in withdrawn.text
    start_search(client, case)
    wait_search(app, client, case["id"])
    refreshed = client.get(endpoint)
    assert not refreshed.json()["mapping"]["stale"]
    assert PENDING in refreshed.text and QUOTE not in refreshed.text


def test_read_before_review_adopts_draft_and_check_original_on_cached_validation(review_app):
    app, client, _, _ = review_app
    case, source = prepared_case(app, count=3)
    assert generate(client, case).status_code == 202
    full = wait_drafts(app, client, case)
    endpoint = url(case, "/requests/P3/preview")
    preview = client.get(endpoint).json()
    assert preview["drafts"]["results"] == [full["results"][2]]
    assert preview["review"]["requests"] == []
    support = preview["mapping"]["results"][0]["supports"][0]
    original = app.state.library.original(source["id"], case["id"])
    original.write_bytes(b"Original manipulado en la copia de prueba.")
    unsafe = client.get(endpoint)
    assert unsafe.json()["mapping"]["stale"] and not unsafe.json()["drafts"]["results"]
    assert support["quote"] not in unsafe.text
