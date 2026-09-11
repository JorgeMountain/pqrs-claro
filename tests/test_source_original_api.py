"""Los originales de imágenes se pueden cotejar sin convertirlos ni descargarlos."""

import hashlib
from io import BytesIO
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pqrs_claro.app import create_app
from pqrs_claro.config import Settings
from pqrs_claro.source_import import HistoryImporter


@pytest.mark.parametrize(
    ("extension", "image_format", "media_type"),
    [
        (".png", "PNG", "image/png"),
        (".jpg", "JPEG", "image/jpeg"),
        (".jpeg", "JPEG", "image/jpeg"),
        (".JPG", "JPEG", "image/jpeg"),
    ],
)
def test_image_original_is_inline_with_unchanged_bytes_and_filename(
    tmp_path, extension, image_format, media_type
):
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app) as client:
        library = app.state.library
        library.save_collection({"id": "test-images", "title": "Imágenes ficticias"})
        with BytesIO() as stream, Image.new("RGB", (12, 9), "navy") as image:
            image.save(stream, format=image_format)
            original_bytes = stream.getvalue()
        filename = "anexo matrícula" + extension
        source, _ = HistoryImporter(library, "test-images").add(
            original_bytes,
            {
                "filename": filename,
                "title": "Anexo de prueba",
                "category": "historical_attachment",
                "origin": "Prueba aislada",
            },
            {"pages": [], "extraction_status": "pending", "location_kind": "section"},
            expected_sha256=hashlib.sha256(original_bytes).hexdigest(),
        )
        before = library.get(source["id"])

        response = client.get(f"/api/sources/{source['id']}/original")

        assert response.status_code == 200
        assert response.content == original_bytes
        assert response.headers["content-type"] == media_type
        assert response.headers["content-disposition"] == (
            f"inline; filename*=utf-8''{quote(filename)}"
        )
        assert library.get(source["id"]) == before
        assert library.original(source["id"]).read_bytes() == original_bytes
