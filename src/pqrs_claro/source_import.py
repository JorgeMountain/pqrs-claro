"""Incorporación idempotente de archivos históricos; ningún original se altera."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .models import DomainError
from .storage import now, write_original

HISTORICAL_CATEGORIES = {
    "historical_response",
    "historical_petition",
    "historical_attachment",
    "archive_only",
    "national_norm",
    "institutional_norm",
}


class HistoryImporter:
    def __init__(self, library, collection_id):
        self.library = library
        self.collection_id = collection_id
        if collection_id not in {c["id"] for c in library.collections()}:
            raise DomainError("Crea la colección antes de incorporar sus archivos.")
        self.existing = {
            s["sha256"]: s for s in library.list() if s.get("collection_id") == collection_id
        }

    def add(self, data, metadata, extraction, *, expected_sha256):
        """Conserva incluso archivos sin lector y todas las procedencias de un duplicado."""
        sha = hashlib.sha256(data).hexdigest()
        if sha != expected_sha256:
            raise DomainError("El archivo cambió desde el inventario. Revisa antes de importarlo.")
        if sha in self.existing:
            with self.library.lock:
                original = self.library.get(self.existing[sha]["id"])["source"]
                self.library.original(original["id"])
                aliases = original.get("aliases", []) + metadata.get("aliases", [])
                seen = set()
                merged = []
                for alias in aliases:
                    identity = json.dumps(alias, sort_keys=True, ensure_ascii=False)
                    if identity not in seen:
                        seen.add(identity)
                        merged.append(alias)
                original["aliases"] = merged
                for key in ("historical_groups", "radicados", "office_numbers"):
                    original[key] = sorted(set(original.get(key, []) + metadata.get(key, [])))
                original["import_notes"] = list(
                    dict.fromkeys(original.get("import_notes", []) + metadata.get("notes", []))
                )
                with self.library.connect() as conn:
                    conn.execute(
                        "UPDATE sources SET body=? WHERE id=?",
                        (json.dumps(original), original["id"]),
                    )
                self.existing[sha] = original
            return original, False
        category = metadata["category"]
        if category not in HISTORICAL_CATEGORIES:
            raise DomainError("El tipo de documento histórico no está reconocido.")
        filename = Path(metadata["filename"].replace("\\", "/")).name
        if not filename:
            raise DomainError("El documento histórico requiere un nombre.")
        pages = extraction.get("pages", [])
        if [p["number"] for p in pages] != list(range(1, len(pages) + 1)):
            raise DomainError(
                "La lectura histórica debe conservar páginas o secciones consecutivas."
            )
        source_id = uuid4().hex
        source = dict(
            id=source_id,
            document_id=source_id,
            version=1,
            filename=filename,
            title=metadata.get("title") or filename,
            category=category,
            case_id=None,
            origin=metadata["origin"],
            sha256=sha,
            created_at=now(),
            review_status="pending",
            validity="unknown" if category.endswith("norm") else "not_applicable",
            reviewed_by=None,
            review_note=None,
            reviewed_at=None,
            page_count=len(pages),
            location_kind=extraction.get("location_kind", "section"),
            collection_id=self.collection_id,
            historical_group=metadata.get("historical_group", "Sin clasificar"),
            historical_groups=metadata.get("historical_groups", []),
            radicados=metadata.get("radicados", []),
            primary_radicado=metadata.get("primary_radicado"),
            identifier_evidence=metadata.get("identifier_evidence", []),
            office_numbers=metadata.get("office_numbers", []),
            document_status=metadata.get("document_status", "unknown"),
            document_date_text=metadata.get("date_text"),
            verification_status="pending",
            verification_note=(
                "El usuario informó que algunas respuestas de esta colección habían sido "
                "verificadas previamente. No se ha identificado el alcance ni el responsable "
                "de esa verificación para este archivo."
            ),
            extraction_status=extraction.get("extraction_status", "unsupported"),
            extraction_note=extraction.get("extraction_note", ""),
            related_source_ids=[],
            aliases=metadata.get("aliases", []),
            import_notes=metadata.get("notes", []),
            classification_basis=metadata.get("classification_basis", ""),
        )
        with self.library.lock:
            folder = self.library.root / source_id
            folder.mkdir()
            path = folder / ("original" + Path(filename).suffix.lower())
            write_original(path, data)
            # Si la base falla, el original se conserva para recuperar la incorporación.
            with self.library.connect() as conn:
                conn.execute(
                    "INSERT INTO sources VALUES (?,?,?,?,?)",
                    (source_id, source_id, 1, json.dumps(source), json.dumps(pages)),
                )
        self.existing[sha] = source
        return {**source, "is_latest": True}, True

    def relate(self, source_id, related_ids, *, basis):
        """Agrupación documental explícita; una relación no declara corroboración probatoria."""
        with self.library.lock:
            source = self.library.get(source_id)["source"]
            if source.get("collection_id") != self.collection_id:
                raise DomainError("La relación no pertenece a esta colección.")
            related_ids = sorted(set(related_ids) - {source_id})
            own_ids = {item["id"] for item in self.existing.values()}
            if not set(related_ids) <= own_ids:
                raise DomainError("No se pueden mezclar colecciones al organizar antecedentes.")
            source.update(related_source_ids=related_ids, relationship_basis=basis)
            with self.library.connect() as conn:
                conn.execute(
                    "UPDATE sources SET body=? WHERE id=?", (json.dumps(source), source_id)
                )
                conn.executemany(
                    "INSERT INTO source_relationships VALUES (?,?,?,?) "
                    "ON CONFLICT(source_id,target_id,kind) DO UPDATE SET body=excluded.body",
                    [
                        (source_id, related, "shared_provenance", json.dumps({"basis": basis}))
                        for related in related_ids
                    ],
                )
        return source
