"""Importa un inventario revisable a una colección local, conservando originales y alias."""

import argparse
import hashlib
import json
import sqlite3
import zipfile
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path

from pqrs_claro.config import Settings
from pqrs_claro.extraction import PDFExtractor
from pqrs_claro.source_import import HistoryImporter
from pqrs_claro.source_library import SourceLibrary
from pqrs_claro.storage import now, write_original


def read_occurrence(item, scope):
    path = Path(item.get("path") or item["zip_path"]).resolve()
    if not any(path == root or (root.is_dir() and path.is_relative_to(root)) for root in scope):
        raise ValueError("Una procedencia sale del conjunto de archivos autorizado.")
    data = path.read_bytes()
    for member in item.get("zip_chain", [item["member"]] if item.get("member") else []):
        with zipfile.ZipFile(BytesIO(data)) as archive:
            info = archive.getinfo(member)
            if info.file_size > 128 * 1024 * 1024 or info.flag_bits & 1:
                raise ValueError("Miembro de archivo cifrado o mayor de 128 MB.")
            data = archive.read(info)
    return data


def run(manifest_path, collection_id, title, data_dir):
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest.decode("utf-8-sig"))
    scope = [Path(path).resolve() for path in manifest["scope"]]
    library = SourceLibrary(data_dir, PDFExtractor())
    backup = data_dir / "backups" / f"before-{collection_id}.sqlite"
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        with library.connect() as origin, sqlite3.connect(backup) as destination:
            origin.backup(destination)
    archive_dir = data_dir / "imports" / collection_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    # El inventario contiene procedencias privadas y queda dentro de data, fuera de Git.
    write_original(archive_dir / "inventory.json", raw_manifest)
    collection = dict(
        id=collection_id,
        title=title,
        status="importing",
        created_at=now(),
        description="Peticiones, respuestas y anexos históricos organizados por su procedencia.",
        verification_note=(
            "El usuario informa que algunas respuestas habían sido verificadas previamente. "
            "El alcance, responsable y fecha de esa verificación aún no están individualizados."
        ),
        verification_status="reported_by_user",
        source_count=0,
        group_count=0,
        provenance_count=len(manifest["occurrences"]),
        inventory_sha256=hashlib.sha256(raw_manifest).hexdigest(),
    )
    existing = next((c for c in library.collections() if c["id"] == collection_id), None)
    if existing:
        collection["created_at"] = existing["created_at"]
    library.save_collection(collection)
    importer = HistoryImporter(library, collection_id)
    sources, by_sha, failed = [], {}, []
    for number, item in enumerate(manifest["unique_documents"], 1):
        try:
            extraction = json.loads(Path(item["extraction_path"]).read_text(encoding="utf-8-sig"))
            groups = sorted(
                {alias["group"].replace("\\", "/").split("/")[0] for alias in item["aliases"]}
            )
            metadata = dict(
                filename=item["filename"],
                title=item["title"],
                category=item["category"],
                origin=f"Colección {title}; aportada por el usuario. "
                f"Procedencias conservadas: {len(item['aliases'])}.",
                historical_group=groups[0],
                historical_groups=groups,
                aliases=item["aliases"],
                radicados=item.get("all_radicados", item.get("radicados", [])),
                primary_radicado=item.get("primary_radicado"),
                identifier_evidence=item.get("identifier_evidence", []),
                office_numbers=item.get("office_numbers", []),
                date_text=item.get("date_text"),
                document_status="draft"
                if item["document_status"] == "draft_or_placeholder"
                else "unknown",
                notes=item.get("notes", []),
                classification_basis=item.get("classification_reason", ""),
            )
            source, created = importer.add(
                read_occurrence(item, scope), metadata, extraction, expected_sha256=item["sha256"]
            )
            sources.append(source)
            by_sha[item["sha256"]] = source["id"]
        except Exception as exc:
            failed.append(
                {"sha256": item["sha256"], "filename": item["filename"], "error": str(exc)[:500]}
            )
        if number % 100 == 0:
            print(
                json.dumps({"processed": number, "saved": len(sources), "failures": len(failed)}),
                flush=True,
            )
    # Las asociaciones conservan su fundamento: carpeta compartida o referencia explícita.
    links = defaultdict(set)
    for group in manifest.get("folder_relations", []):
        anchors = set(group["responses"] + group["petitions"])
        for sha in group["documents"]:
            related = set(group["documents"]) if sha in anchors else anchors
            links[sha].update(related - {sha})
    for relation in manifest.get("document_relations", []):
        left = relation.get("source_sha256")
        right = relation.get("target_sha256")
        if left and right:
            links[left].add(right)
            links[right].add(left)
    for sha, related in links.items():
        if sha in by_sha:
            importer.relate(
                by_sha[sha],
                [by_sha[r] for r in related if r in by_sha],
                basis="Procedencia en la misma carpeta o referencia documental registrada "
                "en el inventario. La relación no acredita envío ni corroboración del hecho.",
            )
    with library.connect() as conn:
        for relation in manifest.get("document_relations", []):
            if relation["source_sha256"] in by_sha and relation["target_sha256"] in by_sha:
                conn.execute(
                    "INSERT INTO source_relationships VALUES (?,?,?,?) "
                    "ON CONFLICT(source_id,target_id,kind) DO UPDATE SET body=excluded.body",
                    (
                        by_sha[relation["source_sha256"]],
                        by_sha[relation["target_sha256"]],
                        relation["type"],
                        json.dumps(relation),
                    ),
                )
    counts = Counter(source["category"] for source in sources)
    extraction_counts = Counter(source["extraction_status"] for source in sources)
    collection.update(
        status="ready" if not failed else "attention",
        source_count=len(sources),
        group_count=len({group for s in sources for group in s["historical_groups"]}),
        category_counts=dict(counts),
        extraction_counts=dict(extraction_counts),
        duplicate_occurrences=manifest["counts"]["duplicate_occurrences"],
        imported_at=now(),
        indexed_count=sum(extraction_counts[k] for k in ("ready", "partial")),
        pending_reading_count=extraction_counts["pending"],
        failure_count=len(failed),
    )
    library.save_collection(collection)
    report = {
        "collection": collection,
        "failures": failed,
        "sources_by_sha256": by_sha,
        "original_bytes": sum(item["bytes"] for item in manifest["unique_documents"]),
    }
    write_original(
        archive_dir / "import-result.json",
        json.dumps(report, ensure_ascii=False, indent=2).encode(),
    )
    print(
        json.dumps(
            {
                "collection_id": collection_id,
                "saved": len(sources),
                "categories": dict(counts),
                "extraction": dict(extraction_counts),
                "failures": len(failed),
                "report": str(archive_dir / "import-result.json"),
            }
        ),
        flush=True,
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--collection-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--data-dir", type=Path, default=Settings.load().data_dir)
    args = parser.parse_args()
    if not args.collection_id.replace("-", "").replace("_", "").isalnum():
        parser.error("Usa letras, números, guiones o guiones bajos para identificar la colección.")
    run(args.manifest, args.collection_id, args.title, args.data_dir)
