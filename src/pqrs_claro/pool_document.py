"""Export the exact text released by the final administrative review."""

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.responses import Response

from .models import DomainError
from .office_models import xml_text
from .office_renderer import write_office_word
from .office_templates import load_letterhead, validate_template_file
from .pool_text import reply_blocks
from .storage import Conflict

# This is the version used by the original four-stage UdeA editor.
_UDEA_TEMPLATE = "a7a81df06ceee7bb7b00443c03ce1293861dffa00b05d2e1d02b1a9bcd029120"


def office_layouts(snapshot, state, data_dir):
    """Return styling for the exact saved versions; the response text stays authoritative."""
    text = snapshot.get("text", "")
    if not text:
        return {}
    letter = snapshot.get("letter") or {}
    original = letter.get("blocks", [])
    candidates = [original] if original else []
    rows = snapshot.get("requests", [])
    if rows and all("text" in row and "answer" in row for row in rows):
        candidates.append(reply_blocks(rows, letter))

    letterhead = letter.get("letterhead")
    if "letterhead" not in letter and original and original[0]["kind"] != "institution":
        # Old imports kept the institutional blocks/metadata, but did not store the
        # template ID. Only use the known UdeA layout with the matching local original.
        metadata = letter.get("metadata", {})
        if (metadata.get("institution"), metadata.get("department")) == (
            "Universidad de Antioquia", "Facultad de Ingeniería"
        ):
            try:
                template = load_letterhead(data_dir)
            except DomainError:
                template = None
            if template and template.sha256 == _UDEA_TEMPLATE:
                letterhead = template.public()

    versions = {
        "draft": text,
        "initial_draft": state.get("initial_draft"),
        "previous_draft": state.get("previous_draft"),
    }
    result = {}
    for blocks in candidates:
        body = "\n\n".join(b["text"] for b in blocks)
        for name, saved in versions.items():
            if body == saved and name not in result:
                kinds = [b["kind"] for b in blocks for _ in b["text"].split("\n\n")]
                result[name] = {"kinds": kinds, "letterhead": letterhead}
    return result


def _saved_template(data_dir, sha256):
    # The active registry can rotate after approval. The original may still be
    # present under its versioned filename in the local template directory.
    folder = Path(data_dir).resolve() / "templates"
    for candidate in folder.glob("*.docx"):
        if candidate.resolve().parent == folder:
            try:
                return validate_template_file(candidate, sha256)
            except DomainError:
                continue
    raise Conflict("La plantilla del oficio aprobado no está disponible en su versión original.")


def approved_document(state, data_dir=None):
    if state["stage"] != "approved":
        raise Conflict("El documento estará disponible después de la aprobación final.")
    layout = state.get("office_layouts", {}).get("draft", {})
    letterhead = layout.get("letterhead")
    if letterhead and data_dir is None:
        raise Conflict(
            "La plantilla del oficio aprobado no está disponible en su versión original."
        )
    template = _saved_template(data_dir, letterhead["sha256"]) if letterhead else None
    parts = xml_text(state["draft"]).split("\n\n")
    saved_kinds = layout.get("kinds") or []
    kinds = saved_kinds if len(saved_kinds) == len(parts) else ["body"] * len(parts)
    blocks = []
    for index, (paragraph, kind) in enumerate(zip(parts, kinds, strict=True)):
        if index:
            blocks.append(dict(kind="separator", text=""))
        blocks.append(dict(kind=kind, text=paragraph))
    with TemporaryDirectory() as folder:
        path = Path(folder) / "respuesta.docx"
        write_office_word(blocks, path, template)
        if template:
            validate_template_file(template, letterhead["sha256"])
        content = path.read_bytes()
    filename = f'Respuesta-{state["case_id"]}.docx'
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
