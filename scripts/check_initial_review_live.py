"""Prueba con IA real, fuentes FIAGA y petición ficticia en la copia de desarrollo."""

import io
import json
import time
from pathlib import Path

import httpx
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "qa" / "initial-review-live"
OUT.mkdir(parents=True, exist_ok=True)
client = httpx.Client(base_url="http://127.0.0.1:8773", timeout=30)
environment = client.get("/fiaga-environment").raise_for_status().json()
assert Path(environment["code_root"]).resolve() == ROOT
assert Path(environment["data_root"]).resolve() == ROOT / "data"
assert client.get("/api/config").json()["initial_review_enabled"]
source_root = ROOT.parent / "Documentos" / "FIAGA_revision_inicial_2026-09-17" / "originales"
existing = {s["filename"] for s in client.get("/api/sources").json()["sources"]}
for filename in [
    "SG-MA-01 MANUAL DE ATENCIÓN AL CIUDADANO.pdf",
    "SG-GU-02 GUÍA PARA EL MEJORAMIENTO DEL SISTEMA DE ATENCIÓN AL CIUDADANO.pdf",
    "SG-PT-01 PROTOCOLO DE ATENCIÓN AL CIUDADANO.pdf",
    "RR 37421 de 2013.pdf",
]:
    if filename not in existing:
        response = client.post(
            "/api/sources",
            files={"file": (filename, (source_root / filename).read_bytes(), "application/pdf")},
            data={
                "title": filename.removesuffix(".pdf"),
                "category": "institutional_norm",
                "origin": (
                    "Correo Atención al Ciudadano 17-09-2026 · Requerimientos FIAGA. "
                    "Vigencia pendiente de comprobación."
                ),
            },
        )
        response.raise_for_status()
pdf = io.BytesIO()
c = canvas.Canvas(pdf)
c.setFont("Helvetica", 12)
lines = [
    "PRUEBA FICTICIA FIAGA - NO CORRESPONDE A UN CIUDADANO REAL",
    "Universidad de Antioquia - Atención al Ciudadano",
    "Solicitante: Persona de prueba FIAGA",
    "Contacto: persona.ficticia@example.invalid",
    "1. Solicito copia del Manual de Atención al Ciudadano de la Universidad.",
    "2. Solicito información sobre los canales institucionales para presentar PQRS.",
    "El servicio me parece pésimo y estoy inconforme con la atención.",
    "No he presentado antes esta solicitud. No adjunto documentos.",
    "Este texto se usa únicamente para validar el funcionamiento del sistema.",
]
for i, line in enumerate(lines):
    c.drawString(38, 790 - i * 28, line)
c.save()
(OUT / "peticion-ficticia.pdf").write_bytes(pdf.getvalue())
case = (
    client.post(
        "/api/cases",
        files={"file": ("PRUEBA FICTICIA FIAGA.pdf", pdf.getvalue(), "application/pdf")},
    )
    .raise_for_status()
    .json()
)
prefix = f"/api/cases/{case['id']}"
(OUT / "caso.json").write_text(
    json.dumps(
        {"case_id": case["id"], "url": "http://127.0.0.1:8773/?case=" + case["id"]}, indent=2
    ),
    encoding="utf-8",
)
client.post(prefix + "/analyze", json={}).raise_for_status()
deadline = time.monotonic() + 240
while time.monotonic() < deadline:
    case = client.get(prefix).raise_for_status().json()
    if case["status"] in {"needs_review", "error"}:
        break
    time.sleep(2)
assert case["status"] == "needs_review", case.get("error")
result = (
    client.post(prefix + "/confirm-and-prepare", json={"version": case["version"]})
    .raise_for_status()
    .json()
)
case = result["case"]
assert result["preparation"]["status"] == "waiting_initial_review"
assert client.get(prefix + "/preparation").json()["status"] == "waiting_initial_review"
client.post(
    prefix + "/initial-review/analyze", json={"version": case["version"], "revision": 0}
).raise_for_status()
print(json.dumps({"case_id": case["id"], "stage": "initial_review_running"}), flush=True)
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    review = client.get(prefix + "/initial-review").raise_for_status().json()
    if review["status"] != "running":
        break
    time.sleep(2)
(OUT / "resultado.json").write_text(
    json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
)
assert review["status"] == "needs_review", review.get("error")
assert not review["can_prepare"]
assert review["policy_version"] == 2
assert {c["key"] for c in review["report"]["document"]["checks"]} == {"requirements", "respect"}
assert all({c["key"] for c in r["checks"]} == {"repetition", "classification"}
           for r in review["report"]["requests"])
assert next(c for c in review["report"]["document"]["checks"]
            if c["key"] == "respect")["state"] != "attention"
assert all(
    next(c for c in r["checks"] if c["key"] == "repetition")["state"] == "unavailable"
    for r in review["report"]["requests"]
)
assert client.get(prefix + "/preparation").json()["status"] == "waiting_initial_review"
print(
    json.dumps(
        {
            "passed": True,
            "requests": len(review["report"]["requests"]),
            "url": "http://127.0.0.1:8773/?case=" + case["id"] + "&step=1",
        },
        ensure_ascii=False,
    ),
    flush=True,
)
