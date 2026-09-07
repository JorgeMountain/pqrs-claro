"""Evalúa únicamente PDFs ficticios con OpenAI real; guarda resultados sin credenciales."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from pqrs_claro.config import Settings
from pqrs_claro.extraction import OpenAIOCR, PDFExtractor
from pqrs_claro.identification import OpenAIIdentifier
from pqrs_claro.models import DomainError, validate_identification

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--case", default="all", help="ID de cases.json; all excluye reservado")
args = parser.parse_args()
settings = Settings.load()
if not settings.api_key:
    raise SystemExit("No hay una clave configurada.")
corpus = json.loads((ROOT / "examples/cases.json").read_text(encoding="utf-8"))
selected = [
    c for c in corpus if (not c.get("holdout") if args.case == "all" else c["id"] == args.case)
]
if not selected:
    raise SystemExit("No existe ese caso de evaluación.")
extractor = PDFExtractor(OpenAIOCR(settings.api_key, settings.model))
identifier = OpenAIIdentifier(settings.api_key, settings.model)
report = dict(
    date=datetime.now(timezone.utc).isoformat(),
    mode="OpenAI real; documentos ficticios",
    model=settings.model,
    results=[],
)
out = ROOT / "output/qa"
out.mkdir(parents=True, exist_ok=True)
for case in selected:
    started = time.monotonic()
    item = dict(id=case["id"], expected=case["expected_count"], passed=False)
    try:
        pages = extractor.extract(str(ROOT / "examples" / case["file"]))
        result = identifier.identify(pages)
        validate_identification(result, pages)
        item["actual"] = len(result.requests)
        item["identification"] = result.model_dump(mode="json")
        item["methods"] = [p.method for p in pages]
        issues = []
        if len(result.requests) != case["expected_count"]:
            issues.append("Cantidad de solicitudes distinta de la referencia humana.")
        for expected in case["expected_requests"]:
            matches = [
                r
                for r in result.requests
                if any(ref.page == expected["page"] for ref in r.source_refs)
                and all(
                    term.casefold() in " ".join(ref.quote for ref in r.source_refs).casefold()
                    for term in expected["terms"]
                )
            ]
            if not matches:
                issues.append(
                    f"Sin correspondencia para página {expected['page']}: {expected['terms']}."
                )
            elif expected.get("parent") and not any(
                r.parent_id == expected["parent"] for r in matches
            ):
                issues.append("Relación con solicitud padre incorrecta.")
        if result.document_date != case.get("expected_date"):
            issues.append("Fecha del documento distinta de la referencia literal.")
        if result.requester is not None:
            issues.append("El conjunto no incluye nombres de solicitantes.")
        if case["id"] == "escaneado" and not all(
            p.method == "ocr" and p.needs_review for p in pages
        ):
            issues.append("El escaneado debe señalar OCR y revisión humana.")
        item["issues"] = issues
        item["passed"] = not issues
    except DomainError as exc:
        item["error"] = str(exc)
        item["passed"] = case["expected_count"] == 0 and "No se encontraron solicitudes" in str(exc)
    except Exception as exc:
        item["error"] = type(exc).__name__
    item["seconds"] = round(time.monotonic() - started, 2)
    report["results"].append(item)
    (out / f"live-{args.case}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in item.items() if k not in {"identification"}}, ensure_ascii=True
        ),
        flush=True,
    )
raise SystemExit(0 if all(r["passed"] for r in report["results"]) else 1)
