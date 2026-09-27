"""Arranque exclusivo de la copia FIAGA; no usa datos de presentación."""
from dataclasses import replace
from pathlib import Path

import uvicorn

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.unified_app import create_unified_app

EXPECTED = Path(__file__).resolve().parents[1]
if ROOT.resolve() != EXPECTED or EXPECTED.name != "pqrs-claro-fiaga":
    raise RuntimeError("Este arranque solo admite el código de la copia FIAGA.")
DATA = EXPECTED / "data"
if DATA.resolve() != EXPECTED / "data":
    raise RuntimeError("Los datos FIAGA no pueden ser un enlace a otra carpeta.")
settings = replace(Settings.load(), data_dir=DATA, port=8773, initial_review_enabled=True,
                   initial_classification_provider="openai", environment_label="Desarrollo FIAGA · datos de prueba independientes")
app = create_unified_app(settings)


@app.get("/fiaga-environment")
def environment():
    return {"environment": "desarrollo-fiaga", "code_root": str(EXPECTED),
            "data_root": str(DATA), "port": 8773}


# La aplicación ya monta los archivos estáticos en /; esta ruta va antes.
app.router.routes.insert(0, app.router.routes.pop())


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8773, access_log=False)
