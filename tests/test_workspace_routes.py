# ruff: noqa: F811
"""La interfaz principal es dinámica y la anterior sigue disponible."""

from test_source_service_api import make_case, pdf_bytes, source_app  # noqa: F401


def test_home_and_previous_interface_are_both_available(source_app):
    _, client, _, _ = source_app
    new = client.get("/")
    old = client.get("/anterior")
    assert new.status_code == old.status_code == 200
    assert "/static/workspace/app.js" in new.text
    assert "/static/app.js" in old.text
    assert "step-upload" in old.text and 'data-stage="3"' in new.text
    script = client.get("/static/workspace/app.js").text
    assert "data.json" not in script and "scope-confirm" not in script
    assert "/review/start" in script and "/drafts/generate" in script
    assert client.get("/static/workspace/presentation.js").status_code == 200


def test_original_highlight_uses_saved_request_and_preserves_pdf(source_app, pdf_bytes):
    app, client, _, _ = source_app
    case = make_case(client, pdf_bytes)
    response = client.get(f"/api/cases/{case['id']}/pages/1/view?request_id=P2")
    assert response.status_code == 200
    view = response.json()
    assert view["version"] == case["version"]
    assert (
        view["marks"][0]["quote"]
        == case["identification"]["requests"][1]["source_refs"][0]["quote"]
    )
    assert view["has_visual_match"]
    for x1, y1, x2, y2 in view["marks"][0]["rectangles"]:
        assert 0 <= x1 < x2 <= view["width"]
        assert 0 <= y1 < y2 <= view["height"]
    assert app.state.store.original(case["id"]).read_bytes() == pdf_bytes
    assert client.get(f"/api/cases/{case['id']}/pages/1/view?request_id=P99").status_code == 404
    assert client.get(f"/api/cases/{case['id']}/pages/99/view").status_code == 404
