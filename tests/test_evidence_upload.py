# ruff: noqa: F811
"""Carga real en SQLite/archivos aislados; solo la evaluación IA usa un doble."""

from test_source_service_api import make_case, pdf_bytes, source_app, wait_search  # noqa: F401


def upload(client, case, content=b"Requisitos de practicas y acta del comite.", **changes):
    fields = dict(
        title="Acta aportada",
        origin="Archivo de prueba local",
        category="case_evidence",
        case_id=case["id"],
        version=case["version"],
        request_id="P2",
    )
    fields.update(changes)
    return client.post(
        "/api/evidence", data=fields, files={"file": ("evidencia.txt", content, "text/plain")}
    )


def test_upload_search_duplicate_and_request_receipt(source_app, pdf_bytes):
    app, client, _, _ = source_app
    case = make_case(client, pdf_bytes)
    first = upload(client, case)
    assert first.status_code == 201, first.text
    receipt = first.json()
    assert receipt["request_id"] == "P2" and not receipt["duplicate"]
    assert receipt["sources_changed"] is True
    result = wait_search(app, client, case["id"])
    assert result["status"] == "ready"
    assert any(
        s["source_id"] == receipt["source_id"] for f in result["results"] for s in f["supports"]
    )
    second = upload(client, case).json()
    assert second["duplicate"] and second["source_id"] == receipt["source_id"]
    assert second["sources_changed"] is False
    assert len(app.state.library.list(case["id"])) == 1
    response = client.get(f"/api/cases/{case['id']}/evidence").json()
    assert len(response["receipts"]) == 2
    assert app.state.store.get(case["id"]) == case  # No edición de identificación ni aprobación.


def test_unreadable_is_retained_and_not_used_as_evidence(source_app, pdf_bytes):
    app, client, assessor, _ = source_app
    case = make_case(client, pdf_bytes)
    response = upload(client, case, b"\x00\xff")
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["extraction_status"] == "error"
    assert receipt["search_status"] == "not_requested"
    source_id = receipt["source_id"]
    assert app.state.library.original(source_id, case["id"]).read_bytes() == b"\x00\xff"
    assert app.state.library.get(source_id, case["id"])["pages"] == []
    assert app.state.library.eligible(case["id"]) == []
    assert not assessor.calls


def test_version_and_private_scope(source_app, pdf_bytes):
    app, client, _, _ = source_app
    first_case = make_case(client, pdf_bytes)
    first = upload(client, first_case).json()
    wait_search(app, client, first_case["id"])
    source = app.state.library.get(first["source_id"], first_case["id"])["source"]
    version = upload(
        client,
        first_case,
        b"Acta del comite: contenido corregido.",
        document_id=source["document_id"],
    ).json()
    assert version["source_version"] == 2
    assert app.state.library.original(first["source_id"], first_case["id"]).is_file()
    wait_search(app, client, first_case["id"])
    second_case = make_case(client, pdf_bytes)
    other = upload(client, second_case).json()
    assert other["source_id"] != first["source_id"] and not other["duplicate"]
    wait_search(app, client, second_case["id"])


def test_stale_and_unknown_request_have_no_side_effects(source_app, pdf_bytes):
    app, client, _, _ = source_app
    case = make_case(client, pdf_bytes)
    assert upload(client, case, version=case["version"] - 1).status_code == 409
    assert upload(client, case, request_id="P99").status_code == 422
    assert not app.state.library.list(case["id"])
    assert not client.get(f"/api/cases/{case['id']}/evidence").json()["receipts"]


def test_historical_library_upload_links_collection_without_claiming_verification(
    source_app, pdf_bytes
):
    app, client, _, _ = source_app
    case = make_case(client, pdf_bytes)
    response = upload(client, case, category="historical_response", shared=True, request_id="")
    assert response.status_code == 201, response.text
    source = app.state.library.get(response.json()["source_id"])["source"]
    assert source["case_id"] is None
    assert source["review_status"] == "pending" and source["document_status"] == "unknown"
    assert source["collection_id"] in app.state.library.linked_collections(case["id"])
    wait_search(app, client, case["id"])
    assert source["id"] in {s["id"] for s in app.state.library.eligible(case["id"])}


def test_api_unavailable_retains_file_and_retry_does_not_duplicate(source_app, pdf_bytes):
    app, client, _, _ = source_app
    case = make_case(client, pdf_bytes)
    from dataclasses import replace

    app.state.sources.settings = replace(app.state.sources.settings, api_key="")
    app.state.sources.assessor = None
    receipt = upload(client, case).json()
    assert receipt["search_status"] == "needs_retry" and receipt["search_error"]
    retry = client.post(
        f"/api/cases/{case['id']}/evidence/{receipt['id']}/search",
        json={"version": case["version"]},
    )
    assert retry.status_code == 202 and retry.json()["search_status"] == "needs_retry"
    assert len(app.state.library.list(case["id"])) == 1
