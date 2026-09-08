"""Importa una selección cotejada de Drive, sin sincronizar ni modificar Drive.

El manifiesto privado contiene collection {id,title,description}, scope (directorios
locales autorizados) y files {local_original,sha256,title,drive_url,drive_id,
drive_folder,category,...} y verification_note (contexto común de la colección).
Las notas específicas van en notes de cada archivo. Los bytes y toda la lectura se
validan antes de escribir. Repetir el mismo inventario conserva revisiones e IDs.
"""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.models import DomainError
from pqrs_claro.source_import import HISTORICAL_CATEGORIES, HistoryImporter
from pqrs_claro.source_library import MAX_SOURCE_BYTES, SourceLibrary, read_source
from pqrs_claro.storage import now, write_original


def run(manifest_path, data_dir):
    raw = Path(manifest_path).read_bytes()
    manifest = json.loads(raw.decode("utf-8-sig"))
    collection_info = manifest["collection"]
    collection_id = collection_info["id"]
    if not collection_id or any(
        c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in collection_id
    ):
        raise DomainError("El identificador de colección debe usar letras, números y guiones.")
    scope = [Path(path).resolve(strict=True) for path in manifest["scope"]]
    extractor = PDFExtractor()  # Lectura local; no solicita OCR ni llamadas de IA.
    if not manifest.get("files") or not str(manifest.get("verification_note", "")).strip():
        raise DomainError("El inventario requiere archivos y el contexto de su verificación.")
    prepared, seen = [], set()
    for item in manifest["files"]:
        if item["category"] not in HISTORICAL_CATEGORIES:
            raise DomainError("El inventario contiene una categoría no reconocida.")
        path = Path(item["local_original"]).resolve(strict=True)
        if path.suffix.lower() != ".pdf" or not any(path.is_relative_to(root) for root in scope):
            raise DomainError("El PDF queda fuera de las carpetas cotejadas.")
        parsed = urlparse(item["drive_url"])
        if parsed.scheme != "https" or parsed.netloc != "drive.google.com":
            raise DomainError("La procedencia debe ser un enlace HTTPS de Drive.")
        data = path.read_bytes()
        if not 0 < len(data) <= MAX_SOURCE_BYTES:
            raise DomainError("Cada PDF debe contener hasta 20 MB.")
        sha = hashlib.sha256(data).hexdigest()
        if sha != item["sha256"] or sha in seen:
            raise DomainError("El inventario repite un original o sus bytes cambiaron.")
        seen.add(sha)
        # La extracción debe leer exactamente los bytes cuyo hash se inventarió.
        # El archivo de origen podría cambiar mientras se consulta otra aplicación.
        with TemporaryDirectory(prefix="pqrs-drive-") as temporary:
            snapshot = Path(temporary) / "original.pdf"
            snapshot.write_bytes(data)
            pages, kind = read_source(snapshot, extractor)
        extraction = dict(
            pages=pages,
            location_kind=kind,
            extraction_status="partial" if any(p["needs_review"] for p in pages) else "ready",
        )
        metadata = dict(
            filename=path.name,
            title=item["title"],
            category=item["category"],
            origin=f"Drive · PQRS_Fuentes / {item['drive_folder']}. {item['drive_url']}",
            historical_group=item["drive_folder"],
            historical_groups=[item["drive_folder"]],
            aliases=[
                dict(
                    path=item["drive_url"],
                    drive_url=item["drive_url"],
                    drive_id=item["drive_id"],
                    group=item["drive_folder"],
                )
            ],
            classification_basis=(
                "Carpeta de Drive y contenido del documento cotejados en el inventario."
            ),
            radicados=item.get("radicados", []),
            primary_radicado=item.get("primary_radicado"),
            office_numbers=item.get("office_numbers", []),
            notes=item.get("notes", []),
            document_status="unknown",
        )
        prepared.append((data, sha, metadata, extraction))
    library = SourceLibrary(Path(data_dir), extractor)
    # Un SHA ya presente en otra colección necesita conciliación explícita de su
    # procedencia. Nunca creamos silenciosamente otra copia con una revisión nueva.
    with library.connect() as conn:
        all_sources = [json.loads(row[0]) for row in conn.execute("SELECT body FROM sources")]
    other = {s["sha256"] for s in all_sources if s.get("collection_id") != collection_id}
    if other.intersection(seen):
        raise DomainError(
            "Un original ya pertenece a otra colección. Concilia su procedencia antes de importar."
        )
    batch_hash = hashlib.sha256(raw).hexdigest()
    archive = Path(data_dir) / "imports" / collection_id / batch_hash
    archive.mkdir(parents=True, exist_ok=True)
    backup = archive / "before.sqlite"
    if not backup.exists():
        with library.connect() as origin, closing(sqlite3.connect(backup)) as destination:
            origin.backup(destination)
    write_original(archive / "inventory.json", raw)
    collection = next((c for c in library.collections() if c["id"] == collection_id), None)
    if collection is None:
        collection = dict(
            **collection_info,
            created_at=now(),
            status="importing",
            verification_status="pending",
            verification_note=manifest["verification_note"],
            source_count=0,
            group_count=0,
            provenance_count=0,
        )
        library.save_collection(collection)
    importer = HistoryImporter(
        library, collection_id, verification_context=manifest["verification_note"]
    )
    result = []
    for data, sha, metadata, extraction in prepared:
        source, created = importer.add(data, metadata, extraction, expected_sha256=sha)
        result.append(dict(source_id=source["id"], sha256=sha, created=created))
    sources = [s for s in library.list() if s.get("collection_id") == collection_id]
    counts = Counter(s["extraction_status"] for s in sources)
    collection.update(
        status="ready",
        source_count=len(sources),
        group_count=len({g for s in sources for g in s.get("historical_groups", [])}),
        provenance_count=sum(len(s.get("aliases", [])) for s in sources),
        category_counts=dict(Counter(s["category"] for s in sources)),
        extraction_counts=dict(counts),
        indexed_count=counts["ready"] + counts["partial"],
        pending_reading_count=counts["pending"],
        failure_count=0,
    )
    if any(s["created"] for s in result):
        collection["imported_at"] = now()
    library.save_collection(collection)
    report = dict(
        collection_id=collection_id,
        manifest_sha256=batch_hash,
        created=sum(s["created"] for s in result),
        sources=result,
        total_sources=collection["source_count"],
        checked_at=now(),
    )
    (archive / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.manifest, args.data_dir), ensure_ascii=False))
