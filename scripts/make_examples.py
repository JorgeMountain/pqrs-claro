"""Genera el conjunto ficticio de evaluación; nunca utiliza datos personales reales."""

import json
from pathlib import Path

import pymupdf
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples"
OUT.mkdir(exist_ok=True)
body = ParagraphStyle(
    "body",
    fontName="Helvetica",
    fontSize=11,
    leading=17,
    textColor=HexColor("#263a35"),
    spaceAfter=14,
)
title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=25)


def build(filename, pages):
    elements = []
    for i, blocks in enumerate(pages):
        if i:
            elements.append(PageBreak())
        elements.extend([Paragraph("EJEMPLO FICTICIO · PRUEBA DEL SISTEMA", body), Spacer(1, 18)])
        for index, block in enumerate(blocks):
            elements.append(Paragraph(block, title if index == 0 else body))
    SimpleDocTemplate(
        str(OUT / filename),
        pagesize=A4,
        rightMargin=54,
        leftMargin=54,
        topMargin=48,
        bottomMargin=48,
    ).build(elements)


build(
    "peticion_ejemplo.pdf",
    [
        [
            "Petición de información",
            "Fecha del documento: 7 de septiembre de 2026.",
            "Dirigida a: Oficina de atención de la Institución Ejemplo.",
            "Este documento es ficticio. No describe trámites ni actuaciones de una entidad real.",
            "1. Solicito que se me informe el procedimiento y los requisitos "
            "para solicitar la revisión "
            "de una inscripción en el programa ficticio Aula Abierta.",
            "2. Solicito que se confirme la fecha de recepción y el estado actual de mi solicitud "
            "ficticia de revisión, identificada como EJEMPLO-042. No conozco esos datos.",
        ],
        [
            "Petición de información - continuación",
            "3. Solicito que se me entregue copia completa del acta de la reunión "
            "ficticia del comité "
            "Aula Abierta en la que se estudió el caso EJEMPLO-042.",
            "No se adjunta el acta ni se afirma que la reunión haya ocurrido. "
            "Es un escenario de prueba.",
            "No se incluye nombre de solicitante. No hay fecha de recepción acreditada.",
        ],
    ],
)

build(
    "subapartados.pdf",
    [
        [
            "Petición con apartados",
            "Documento ficticio para evaluar la separación de solicitudes.",
            "1. Solicito información sobre el trámite ficticio de préstamo de equipos:",
            "a) Indicar cuáles son los requisitos y documentos necesarios.",
        ],
        [
            "Continuación de la solicitud 1",
            "b) Informar cuál es el plazo para presentar la solicitud.",
            "2. Solicito copia del formulario ficticio para pedir el préstamo.",
        ],
    ],
)

build(
    "sin_fecha.pdf",
    [
        [
            "Petición sin fecha",
            "Documento ficticio. No contiene nombre ni fecha.",
            "Solicito información sobre el horario de atención de la Oficina Ejemplo.",
        ]
    ],
)
build(
    "no_solicitud.pdf",
    [
        [
            "Nota de contexto",
            "Documento ficticio sin petición dirigida a la entidad.",
            "El proyecto de ejemplo contiene una oficina, dos aulas y un archivo.",
            "Este texto describe un escenario de práctica.",
        ]
    ],
)
build(
    "reservado.pdf",
    [
        [
            "Petición de evaluación reservada",
            "Fecha: 2 de septiembre de 2026. Documento ficticio.",
            "Solicito conocer el nombre del área encargada del programa ficticio Semilla.",
            "También solicito copia de la convocatoria de ese programa.",
        ]
    ],
)

with pymupdf.open(OUT / "sin_fecha.pdf") as native:
    scanned = pymupdf.open()
    for page in native:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.8, 1.8), alpha=False)
        target = scanned.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=pix.tobytes("png"))
    scanned.save(OUT / "escaneado.pdf")
    scanned.close()

cases = [
    dict(
        id="principal",
        file="peticion_ejemplo.pdf",
        expected_count=3,
        expected_requests=[
            dict(page=1, terms=["procedimiento", "requisitos"]),
            dict(page=1, terms=["fecha", "estado"]),
            dict(page=2, terms=["copia", "acta"]),
        ],
        expected_date="7 de septiembre de 2026",
        expected_requester=None,
        expected_evidence=[
            "Reglas del trámite, por verificar en parte 4",
            "Información atribuida al responsable del caso",
            "Archivo del acta; una declaración no reemplaza la copia",
        ],
    ),
    dict(
        id="apartados",
        file="subapartados.pdf",
        expected_count=4,
        expected_requests=[
            dict(page=1, terms=["préstamo"]),
            dict(page=1, terms=["requisitos", "documentos"], parent="P1"),
            dict(page=2, terms=["plazo"], parent="P1"),
            dict(page=2, terms=["copia", "formulario"]),
        ],
        expected_date=None,
    ),
    dict(
        id="sin_fecha",
        file="sin_fecha.pdf",
        expected_count=1,
        expected_requests=[dict(page=1, terms=["horario"])],
        expected_date=None,
    ),
    dict(
        id="escaneado",
        file="escaneado.pdf",
        expected_count=1,
        expected_requests=[dict(page=1, terms=["horario"])],
        expected_date=None,
        notes="OCR obligatorio, revisión contra imagen original.",
    ),
    dict(
        id="sin_solicitud",
        file="no_solicitud.pdf",
        expected_count=0,
        expected_requests=[],
        expected_date=None,
        notes="Debe explicar que no identificó solicitudes; nunca inventarlas.",
    ),
    dict(
        id="reservado",
        file="reservado.pdf",
        expected_count=2,
        expected_requests=[
            dict(page=1, terms=["área", "Semilla"]),
            dict(page=1, terms=["copia", "convocatoria"]),
        ],
        expected_date="2 de septiembre de 2026",
        holdout=True,
        notes="Usar después de fijar instrucciones, sin ajustar el prompt a este resultado.",
    ),
]
(OUT / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Se generaron {len(cases)} PDFs ficticios y su referencia de evaluación.")
