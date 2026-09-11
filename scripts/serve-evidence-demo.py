"""Sirve el recorrido con carga real contra una copia QA explícita."""

import argparse
from dataclasses import replace
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from pqrs_claro.app import create_app
from pqrs_claro.config import ROOT, Settings

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", type=Path, required=True)
parser.add_argument("--case", required=True)
parser.add_argument("--port", type=int, default=8772)
args = parser.parse_args()
if not args.data_dir.resolve().is_relative_to((ROOT / "output" / "qa").resolve()):
    raise ValueError("La demostración conectada requiere una copia bajo output/qa.")
app = create_app(replace(Settings.load(), data_dir=args.data_dir.resolve(), port=args.port))
app.state.store.get(args.case)
prototype = ROOT / "output" / "ux-peticiones-20260910"
static = ROOT / "src" / "pqrs_claro" / "static"
app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != "/"]


@app.get("/")
def home():
    return RedirectResponse(f"/recorrido/?case={args.case}")


@app.get("/recorrido/evidence-upload.js")
def evidence_js():
    return FileResponse(static / "evidence-upload.js", media_type="text/javascript")


@app.get("/recorrido/evidence-upload.css")
def evidence_css():
    return FileResponse(static / "evidence-upload.css", media_type="text/css")


app.mount("/recorrido", StaticFiles(directory=prototype, html=True), name="recorrido")
uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
