"""Plantillas locales versionadas; el original institucional nunca se modifica."""

from __future__ import annotations

import hashlib
import json
import posixpath
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

import pymupdf
from docx.oxml.ns import qn
from lxml import etree
from pydantic import Field, ValidationError, field_validator

from .models import DomainError, StrictModel
from .office_models import Hash, xml_text

_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_REGISTRY_VERSION = 1
_EDITABLE_PARTS = {"word/document.xml", "docProps/core.xml"}


class PublicLetterhead(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    name: str = Field(min_length=1, max_length=200)
    sha256: Hash
    source_url: str = Field(min_length=1, max_length=1000)

    @field_validator("name")
    @classmethod
    def name_text(cls, value):
        value = xml_text(value).strip()
        if not value or ":\\" in value or ":/" in value:
            raise ValueError("El nombre del membrete no debe ser una ruta.")
        return value

    @field_validator("source_url")
    @classmethod
    def source(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("El origen del membrete debe ser una URL HTTPS válida.")
        return value


class _Registry(PublicLetterhead):
    version: int = Field(ge=_REGISTRY_VERSION, le=_REGISTRY_VERSION)
    filename: str = Field(min_length=1, max_length=200)

    @field_validator("filename")
    @classmethod
    def local_name(cls, value):
        if (
            PureWindowsPath(value).name != value
            or PurePosixPath(value).name != value
            or ":" in value
            or not value.casefold().endswith(".docx")
        ):
            raise ValueError("La plantilla debe ser un DOCX del directorio de membretes.")
        return value


@dataclass(frozen=True)
class Letterhead:
    id: str
    name: str
    sha256: str
    source_url: str
    path: Path

    def public(self) -> dict:
        return dict(id=self.id, name=self.name, sha256=self.sha256, source_url=self.source_url)


def validate_letterhead(value: dict) -> dict:
    try:
        return PublicLetterhead.model_validate(value).model_dump()
    except (ValidationError, ValueError):
        raise DomainError("La identidad del membrete no es válida.") from None


def validate_template_file(path: Path, expected_sha256: str) -> Path:
    path = Path(path).resolve()
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError
    except (OSError, ValueError):
        raise DomainError(
            "El membrete configurado falta o cambió de contenido. "
            "Revisa su versión antes de generar."
        ) from None
    return path


def load_letterhead(data_dir: Path) -> Letterhead | None:
    folder = Path(data_dir).resolve() / "templates"
    registry = folder / "active.json"
    if not registry.exists():
        return None
    try:
        value = _Registry.model_validate(json.loads(registry.read_text(encoding="utf-8-sig")))
        path = (folder / value.filename).resolve()
        if path.parent != folder:
            raise ValueError
    except (OSError, ValueError, ValidationError):
        raise DomainError("La configuración del membrete activo no es válida.") from None
    validate_template_file(path, value.sha256)
    return Letterhead(value.id, value.name, value.sha256, value.source_url, path)


def _xml(data: bytes):
    return etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))


def _visible_part(part):
    """Word usa Choice; Fallback no representa una segunda copia del texto."""
    part = deepcopy(part)
    for alternate in list(part.iter(f"{{{_MC}}}AlternateContent")):
        choices = alternate.findall(f"{{{_MC}}}Choice")
        choice = choices[0] if choices else alternate.find(f"{{{_MC}}}Fallback")
        if choice is None:
            raise DomainError("El membrete tiene un elemento alternativo sin contenido.")
        parent, position = alternate.getparent(), alternate.getparent().index(alternate)
        for item in list(choice):
            parent.insert(position, item)
            position += 1
        parent.remove(alternate)
    return part


def _static_text(part) -> str:
    lines = []
    for paragraph in part.iter(qn("w:p")):
        if paragraph.find(f".//{qn('w:p')}") is not None:
            continue
        text = ""
        for element in paragraph.iter():
            if element.tag == qn("w:t"):
                text += element.text or ""
            elif element.tag in {qn("w:br"), qn("w:tab")}:
                text += " "
        if text.strip():
            lines.append(text)
    return "\n".join(lines)


def image_pixels(pixmap) -> bytes:
    """Píxeles RGB visibles sobre papel blanco, incluida la máscara alfa."""
    if pixmap.width * pixmap.height > 4_000_000:
        raise DomainError("La imagen del membrete supera el límite de cuatro millones de píxeles.")
    if pixmap.colorspace is None or pixmap.colorspace.n != 3:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
    data = pixmap.samples
    if not pixmap.alpha:
        return data
    return bytes(
        min(255, data[offset + channel] + 255 - data[offset + 3])
        for offset in range(0, len(data), 4)
        for channel in range(3)
    )


def _part_images(package, part, part_name, kind):
    rel_name = posixpath.join(
        posixpath.dirname(part_name), "_rels", posixpath.basename(part_name) + ".rels"
    )
    blips = list(part.iter(qn("a:blip")))
    if not blips:
        return []
    relations = {item.get("Id"): item for item in _xml(package.read(rel_name))}
    result = []
    for blip in blips:
        relation = relations[blip.get(qn("r:embed"))]
        if relation.get("TargetMode") == "External":
            raise ValueError
        target = relation.get("Target")
        name = (
            target.lstrip("/")
            if target.startswith("/")
            else posixpath.normpath(posixpath.join(posixpath.dirname(part_name), target))
        )
        data = package.read(name)
        pixmap = pymupdf.Pixmap(data)
        bbox = None
        anchor = next(
            (parent for parent in blip.iterancestors() if parent.tag == f"{{{_WP}}}anchor"), None
        )
        if anchor is not None:
            horizontal, vertical = (
                anchor.find(f"{{{_WP}}}positionH"),
                anchor.find(f"{{{_WP}}}positionV"),
            )
            if horizontal.get("relativeFrom") != "page" or vertical.get("relativeFrom") != "page":
                raise ValueError
            x = float(horizontal.find(f"{{{_WP}}}posOffset").text) / 12700
            y = float(vertical.find(f"{{{_WP}}}posOffset").text) / 12700
            extent = anchor.find(f"{{{_WP}}}extent")
            bbox = (x, y, x + float(extent.get("cx")) / 12700, y + float(extent.get("cy")) / 12700)
        result.append(
            dict(
                part=name,
                region=kind,
                width=pixmap.width,
                height=pixmap.height,
                pixels=image_pixels(pixmap),
                bbox=bbox,
            )
        )
    return result


def template_profile(path: Path) -> dict:
    """Perfil comprobable de una sección con encabezado y pie estáticos."""
    try:
        with ZipFile(path) as package:
            if sum(info.file_size for info in package.infolist()) > 30 * 1024 * 1024:
                raise ValueError
            names = package.namelist()
            if len(names) != len(set(names)) or any(
                name.startswith("word/comments") or name.endswith("vbaProject.bin")
                for name in names
            ):
                raise ValueError
            root = _xml(package.read("word/document.xml"))
            body = root.find(qn("w:body"))
            sections = root.findall(f".//{qn('w:sectPr')}")
            if len(sections) != 1 or sections[0].getparent() is not body:
                raise ValueError
            section = sections[0]
            if section.find(qn("w:titlePg")) is not None:
                raise ValueError
            settings = _xml(package.read("word/settings.xml"))
            if settings.find(qn("w:evenAndOddHeaders")) is not None:
                raise ValueError
            size, margins = section.find(qn("w:pgSz")), section.find(qn("w:pgMar"))
            width, height = float(size.get(qn("w:w"))) / 20, float(size.get(qn("w:h"))) / 20
            top = float(margins.get(qn("w:top"))) / 20
            bottom = height - float(margins.get(qn("w:bottom"))) / 20
            relations = {
                relation.get("Id"): relation
                for relation in _xml(package.read("word/_rels/document.xml.rels"))
            }
            regions, images = [], []
            for kind in ("header", "footer"):
                references = section.findall(qn(f"w:{kind}Reference"))
                if len(references) > 1:
                    raise ValueError
                part_names, text = [], ""
                boundary = top if kind == "header" else bottom
                for reference in references:
                    if reference.get(qn("w:type")) != "default":
                        raise ValueError
                    relation = relations[reference.get(qn("r:id"))]
                    if relation.get("TargetMode") == "External":
                        raise ValueError
                    target = relation.get("Target")
                    part_name = target.lstrip("/") if target.startswith("/") else "word/" + target
                    part = _visible_part(_xml(package.read(part_name)))
                    images.extend(_part_images(package, part, part_name, kind))
                    if list(part.iter(qn("w:instrText"))) or list(part.iter(qn("w:fldSimple"))):
                        raise ValueError
                    text = _static_text(part)
                    part_names.append(part_name)
                    for anchor in part.iter(f"{{{_WP}}}anchor"):
                        vertical = anchor.find(f"{{{_WP}}}positionV")
                        offset = vertical.find(f"{{{_WP}}}posOffset")
                        if vertical.get("relativeFrom") != "page" or offset is None:
                            raise ValueError
                        y = float(offset.text) / 12700
                        extent = anchor.find(f"{{{_WP}}}extent")
                        if kind == "header":
                            boundary = max(boundary, y + float(extent.get("cy")) / 12700)
                        else:
                            boundary = min(boundary, y)
                regions.append(dict(kind=kind, text=text, boundary=boundary, parts=part_names))
            if not 0 < regions[0]["boundary"] < regions[1]["boundary"] < height:
                raise ValueError
            first = body.find(qn("w:p"))
            return dict(
                page_width=width,
                page_height=height,
                regions=regions,
                images=images,
                section=etree.tostring(section, method="c14n", exclusive=True),
                paragraph_properties=deepcopy(first.find(qn("w:pPr")))
                if first is not None
                else None,
            )
    except (OSError, ValueError, KeyError, AttributeError, BadZipFile, etree.XMLSyntaxError):
        raise DomainError(
            "El membrete debe ser un DOCX íntegro con una sección y encabezado y pie estáticos."
        ) from None


def verify_preserved_template(template_path: Path, output_path: Path) -> bool:
    with ZipFile(template_path) as original, ZipFile(output_path) as generated:
        if set(original.namelist()) != set(generated.namelist()) or any(
            original.read(name) != generated.read(name)
            for name in original.namelist()
            if name not in _EDITABLE_PARTS
        ):
            raise DomainError("El Word alteró una parte protegida del membrete original.")
    if template_profile(template_path)["section"] != template_profile(output_path)["section"]:
        raise DomainError("El Word alteró la geometría o referencias de sección del membrete.")
    return True
