"""Vista de comprobación con datos separados, sin detener el servidor FIAGA."""

from dataclasses import replace

import uvicorn

from pqrs_claro.config import ROOT, Settings
from pqrs_claro.unified_app import create_unified_app

if ROOT.name != "pqrs-claro-fiaga":
    raise RuntimeError("Este arranque pertenece a la copia FIAGA.")
DATA = ROOT / "output" / "qa" / "fiaga-phase2" / "data"
if DATA.resolve() != DATA or not (DATA / "expedientes.sqlite").is_file():
    raise RuntimeError("Primero debe existir la copia independiente de datos de prueba.")
app = create_unified_app(
    replace(
        Settings.load(),
        data_dir=DATA,
        port=8774,
        initial_review_enabled=True,
        initial_classification_provider="jev",
        environment_label="Desarrollo FIAGA · datos de prueba independientes",
    )
)


@app.get("/fiaga-environment")
def environment():
    return {
        "environment": "desarrollo-fiaga-fase2",
        "code_root": str(ROOT),
        "data_root": str(DATA),
        "port": 8774,
    }


app.router.routes.insert(0, app.router.routes.pop())

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8774, access_log=False)
