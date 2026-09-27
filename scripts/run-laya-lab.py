"""Arranque aislado del banco de pruebas con Laya."""

from pathlib import Path

import uvicorn

from pqrs_claro.config import ROOT
from pqrs_claro.laya_lab import PORT, create_laya_lab_app

EXPECTED = Path(__file__).resolve().parents[1]
if ROOT.resolve() != EXPECTED or EXPECTED.name != "pqrs-claro-fiaga":
    raise RuntimeError("Este banco solo puede arrancar desde la copia aislada FIAGA.")

app = create_laya_lab_app()

if __name__ == "__main__":
    print("Banco temporal FIAGA + Laya: http://127.0.0.1:8775/", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False)
