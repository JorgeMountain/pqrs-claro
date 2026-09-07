"""Biblioteca local: originales inmutables, versiones, procedencia y fragmentos exactos."""

import hashlib
import json
import sqlite3
import textwrap
import threading
import zipfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pymupdf

from .models import DomainError
from .storage import now, write_original

CATEGORIES = {"national_norm", "institutional_norm", "case_evidence", "previous_response"}
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_SOURCE_PAGES = 300
MAX_SOURCE_TEXT = 2_000_000


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def read_source(path, pdf_extractor):
    """PDF conserva páginas; DOCX y TXT conservan secciones, nunca páginas inventadas."""
    path = Path(path)
    if path.suffix == ".pdf":
        try:
            with pymupdf.open(path) as doc:
                if not doc.is_pdf or doc.needs_pass or not 1 <= len(doc) <= MAX_SOURCE_PAGES:
                    raise DomainError(
                        "La fuente debe ser un PDF sin contraseña de 1 a 300 páginas."
                    )
                pages = []
                total = 0
                for page in doc:
                    value = pdf_extractor._read_page(page).model_dump()
                    total += len(value["text"])
                    if total > MAX_SOURCE_TEXT:
                        raise DomainError("La fuente supera dos millones de caracteres.")
                    pages.append(value)
        except (pymupdf.FileDataError, RuntimeError):
            raise DomainError("No se pudo leer el PDF de la fuente.") from None
        kind = "page"
    else:
        if path.suffix == ".docx":
            from docx import Document

            try:
                with zipfile.ZipFile(path) as archive:
                    if sum(item.file_size for item in archive.infolist()) > 80 * 1024 * 1024:
                        raise DomainError("El DOCX descomprimido supera el límite de 80 MB.")
                document = Document(BytesIO(path.read_bytes()))
                blocks = []
                # iter_inner_content preserva el orden de párrafos y tablas.
                for block in document.iter_inner_content():
                    if hasattr(block, "rows"):
                        blocks.extend(
                            " | ".join(cell.text for cell in row.cells) for row in block.rows
                        )
                    else:
                        blocks.append(block.text)
                # No silenciar texto presente en zonas que este lector no interpreta.
                if any(document.part.element.xpath(".//w:txbxContent")):
                    raise DomainError(
                        "El DOCX contiene cuadros de texto. Conviértelo a PDF para conservarlos."
                    )
                text = "\n".join(blocks)
            except (zipfile.BadZipFile, KeyError, ValueError) as exc:
                if isinstance(exc, DomainError):
                    raise
                raise DomainError("El archivo DOCX está dañado o no puede leerse.") from None
        else:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                raise DomainError(
                    "Guarda el TXT con codificación UTF-8 e inténtalo otra vez."
                ) from None
            if "\x00" in text:
                raise DomainError("El archivo no contiene texto UTF-8 válido.")
        if len(text) > MAX_SOURCE_TEXT:
            raise DomainError("La fuente supera dos millones de caracteres.")
        # El texto normalizado es visible junto al original; líneas estables para citar.
        lines = []
        for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
            lines.extend(
                textwrap.wrap(line, width=180, replace_whitespace=False, drop_whitespace=False)
                or [""]
            )
        pages = [
            dict(
                number=i // 40 + 1,
                text="\n".join(lines[i : i + 40]),
                method="native",
                needs_review=False,
            )
            for i in range(0, len(lines), 40)
        ]
        kind = "section"
    if not any(page["text"].strip() for page in pages):
        raise DomainError("La fuente no contiene texto legible.")
    if any(len(line) > 8000 for page in pages for line in page["text"].splitlines()):
        raise DomainError("La fuente contiene líneas demasiado largas. Revisa su formato de texto.")
    return pages, kind


def make_chunks(source, pages):
    # Las rutas originales y los alias sirven al catálogo, no a la evaluación con IA.
    source = {
        key: value
        for key, value in source.items()
        if key not in {"aliases", "historical_groups", "import_notes", "excerpt"}
    }
    chunks = []
    for page in pages:
        lines = page["text"].splitlines()
        start = 0
        while start < len(lines):
            end, size = start, 0
            while end < len(lines) and (size < 1800 or end == start):
                size += len(lines[end]) + 1
                end += 1
            quote = "\n".join(lines[start:end])
            if quote.strip():
                chunks.append(
                    {
                        **source,
                        "source_id": source["id"],
                        "chunk_id": f"{source['id']}:{page['number']}:{start + 1}:{end}",
                        "page": page["number"],
                        "line_start": start + 1,
                        "line_end": end,
                        "quote": quote,
                        "method": page["method"],
                        "needs_review": page["needs_review"],
                    }
                )
            start = max(start + 1, end - 2) if end < len(lines) else end
    return chunks


class SourceLibrary:
    def __init__(self, data_dir, pdf_extractor):
        self.root = Path(data_dir) / "library"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = Path(data_dir) / "biblioteca.sqlite"
        self.pdf_extractor = pdf_extractor
        self.lock = threading.RLock()
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, document_id TEXT,
                    version INTEGER, body TEXT, pages TEXT, UNIQUE(document_id,version));
                CREATE TABLE IF NOT EXISTS source_reviews(id TEXT, created_at TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS source_runs(
                    id TEXT PRIMARY KEY, case_id TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS source_collections(id TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS case_source_collections(
                    case_id TEXT, collection_id TEXT, PRIMARY KEY(case_id,collection_id));
                CREATE TABLE IF NOT EXISTS source_relationships(
                    source_id TEXT, target_id TEXT, kind TEXT, body TEXT,
                    PRIMARY KEY(source_id,target_id,kind));
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def list(self, case_id=None):
        with self.connect() as conn:
            rows = conn.execute("SELECT body FROM sources ORDER BY rowid DESC").fetchall()
        sources = [json.loads(row[0]) for row in rows]
        latest = {}
        for source in sources:
            latest[source["document_id"]] = max(
                source["version"], latest.get(source["document_id"], 0)
            )
        return [
            {**s, "is_latest": s["version"] == latest[s["document_id"]]}
            for s in sources
            if s["case_id"] is None or s["case_id"] == case_id
        ]

    def get(self, source_id, case_id=None):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body,pages,(SELECT max(other.version) FROM sources other "
                "WHERE other.document_id=sources.document_id) FROM sources WHERE id=?",
                (source_id,),
            ).fetchone()
        if not row:
            raise KeyError("Fuente no encontrada.")
        source, pages = json.loads(row[0]), json.loads(row[1])
        if source["case_id"] is not None and source["case_id"] != case_id:
            raise KeyError("Fuente no encontrada en este expediente.")
        source["is_latest"] = source["version"] == row[2]
        return {"source": source, "pages": pages}

    def original(self, source_id, case_id=None):
        source = self.get(source_id, case_id)["source"]
        path = self.root / source_id / ("original" + Path(source["filename"]).suffix.lower())
        if not path.is_file():
            raise DomainError(
                "Falta el original de esta fuente. Restaura su copia antes de buscar."
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise DomainError("El original cambió fuera de la biblioteca. Carga una nueva versión.")
        return path

    def add(self, filename, data, *, title, category, origin, case_id=None, document_id=None):
        filename = Path(filename.replace("\\", "/")).name[:180]
        extension = Path(filename).suffix.lower()
        if extension not in {".pdf", ".docx", ".txt"}:
            raise DomainError("Selecciona una fuente PDF, DOCX o TXT.")
        if not data or len(data) > MAX_SOURCE_BYTES:
            raise DomainError("Selecciona una fuente de hasta 20 MB.")
        if category not in CATEGORIES or not title.strip() or not origin.strip():
            raise DomainError("Indica título, tipo y procedencia de la fuente.")
        if category == "case_evidence" and not case_id:
            raise DomainError("Un soporte del caso debe asociarse a un expediente.")
        sha = hashlib.sha256(data).hexdigest()
        with self.lock:
            previous = [s for s in self.list(case_id) if s["document_id"] == document_id]
            if document_id and not previous:
                raise KeyError("Documento no encontrado.")
            if previous:
                last = max(previous, key=lambda s: s["version"])
                if last["case_id"] != case_id or last["category"] != category:
                    raise DomainError(
                        "La nueva versión debe conservar el tipo y expediente del documento."
                    )
                if last["sha256"] == sha:
                    return last
            source_id = uuid4().hex
            folder = self.root / source_id
            folder.mkdir()
            path = folder / ("original" + extension)
            write_original(path, data)
            try:
                pages, kind = read_source(path, self.pdf_extractor)
                source = dict(
                    id=source_id,
                    document_id=document_id or uuid4().hex,
                    version=last["version"] + 1 if previous else 1,
                    filename=filename,
                    title=title.strip()[:300],
                    category=category,
                    case_id=case_id,
                    origin=origin.strip()[:2000],
                    sha256=sha,
                    created_at=now(),
                    review_status="pending",
                    validity="unknown",
                    reviewed_by=None,
                    review_note=None,
                    reviewed_at=None,
                    page_count=len(pages),
                    location_kind=kind,
                )
                with self.connect() as conn:
                    conn.execute(
                        "INSERT INTO sources VALUES (?,?,?,?,?)",
                        (
                            source_id,
                            source["document_id"],
                            source["version"],
                            json.dumps(source),
                            json.dumps(pages),
                        ),
                    )
            except Exception:
                path.unlink(missing_ok=True)
                folder.rmdir()
                raise
        return {**source, "is_latest": True}

    def review(self, source_id, *, case_id=None, reviewed_by, review_note, validity):
        if not reviewed_by.strip() or not review_note.strip():
            raise DomainError(
                "Indica quién revisó la fuente y cómo comprobó su contenido y procedencia."
            )
        if validity not in {"unknown", "current", "superseded", "not_applicable"}:
            raise DomainError("Selecciona un estado de vigencia válido.")
        with self.lock:
            source = self.get(source_id, case_id)["source"]
            if (
                source["category"] in {"national_norm", "institutional_norm"}
                and validity == "not_applicable"
            ):
                raise DomainError("Una norma requiere comprobar vigencia o dejarla pendiente.")
            source.update(
                reviewed_by=reviewed_by.strip()[:200],
                review_note=review_note.strip()[:3000],
                validity=validity,
                review_status="reviewed",
                reviewed_at=now(),
            )
            if source.get("collection_id"):
                source["verification_status"] = "documented"
                source["verification_note"] = review_note.strip()[:3000]
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO source_reviews VALUES (?,?,?)",
                    (source_id, now(), json.dumps(source)),
                )
                conn.execute(
                    "UPDATE sources SET body=? WHERE id=?", (json.dumps(source), source_id)
                )
        return source

    def snapshot(self, case_id):
        with self.lock:
            sources = self.eligible(case_id)
            source_ids = {s["id"] for s in sources}
            with self.connect() as conn:
                rows = conn.execute("SELECT id,pages FROM sources").fetchall()
            pages = {row[0]: json.loads(row[1]) for row in rows if row[0] in source_ids}
            chunks = []
            for source in sources:
                path = (
                    self.root
                    / source["id"]
                    / ("original" + Path(source["filename"]).suffix.lower())
                )
                if (
                    not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]
                ):
                    raise DomainError(
                        "Un original cambió o falta en la biblioteca. Restaura su copia."
                    )
                chunks.extend(make_chunks(source, pages[source["id"]]))
            return sources, chunks

    def collections(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM source_collections ORDER BY rowid DESC"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_collection(self, collection):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO source_collections VALUES (?,?) "
                "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (collection["id"], json.dumps(collection)),
            )

    def linked_collections(self, case_id):
        with self.connect() as conn:
            return [
                row[0]
                for row in conn.execute(
                    "SELECT collection_id FROM case_source_collections WHERE case_id=? "
                    "ORDER BY collection_id",
                    (case_id,),
                ).fetchall()
            ]

    def link_collections(self, case_id, collection_ids):
        if len(collection_ids) != len(set(collection_ids)):
            raise DomainError("No repitas una colección en la selección.")
        with self.lock, self.connect() as conn:
            available = {row[0] for row in conn.execute("SELECT id FROM source_collections")}
            if not set(collection_ids) <= available:
                raise DomainError("No se encontró una de las colecciones seleccionadas.")
            conn.execute("DELETE FROM case_source_collections WHERE case_id=?", (case_id,))
            conn.executemany(
                "INSERT INTO case_source_collections VALUES (?,?)",
                [(case_id, item) for item in collection_ids],
            )
        return sorted(collection_ids)

    def eligible(self, case_id):
        linked = set(self.linked_collections(case_id))
        return [
            s
            for s in self.list(case_id)
            if s["is_latest"]
            and s["category"] not in {"previous_response", "archive_only"}
            and s["validity"] != "superseded"
            and s.get("extraction_status", "ready") in {"ready", "partial"}
            and (not s.get("collection_id") or s["collection_id"] in linked)
        ]

    def save_run(self, run):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO source_runs VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (run["id"], run["case_id"], json.dumps(run)),
            )

    def latest_run(self, case_id):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body FROM source_runs WHERE case_id=? ORDER BY rowid DESC LIMIT 1",
                (case_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def recover(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT body FROM source_runs").fetchall()
        for row in rows:
            run = json.loads(row[0])
            if run["status"] == "running":
                run.update(
                    status="error",
                    error="La búsqueda se interrumpió. Reintenta para recuperar el avance.",
                )
                self.save_run(run)
