"""Comprueba el análisis automático con datos nuevos, sin alterar la vista anterior."""

from dataclasses import replace

import uvicorn

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.unified_app import create_unified_app

DATA = ROOT / "output" / "qa" / "fiaga-auto-analysis" / "data"
PORT = 8776
app = create_unified_app(replace(
    Settings.load(), data_dir=DATA, port=PORT, initial_review_enabled=True,
    initial_classification_provider="openai", environment_label="Desarrollo FIAGA · datos de prueba independientes",
))


@app.get("/fiaga-environment")
def environment():
    return {
        "environment": "desarrollo-fiaga-analisis-automatico", "code_root": str(ROOT),
        "data_root": str(DATA), "port": PORT,
    }


app.router.routes.insert(0, app.router.routes.pop())

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False)
