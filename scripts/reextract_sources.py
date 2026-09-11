"""Inventaría/prepara/aplica OCR local. Preparar no escribe en la biblioteca."""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from pqrs_claro.models import DomainError
from pqrs_claro.source_reextract import (
    PLAN_VERSION,
    apply_plan,
    is_candidate,
    prepare_source,
    read_rows,
    save_plan,
    state_digest,
)
from pqrs_claro.storage import now
from pqrs_claro.windows_ocr import WindowsOCR


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inventory", "prepare", "apply"])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--collection", action="append", dest="collections")
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--language", default="es-ES")
    parser.add_argument("--kind", choices=["pdf", "images"], default="pdf")
    args = parser.parse_args()
    collections = args.collections or ["onman-20260907", "drive-pqrs-fuentes"]
    if args.command in {"prepare", "apply"} and args.plan is None:
        parser.error("Indica --plan para conservar la propuesta auditable.")
    if args.command == "apply":
        if args.backup is None:
            parser.error("La aplicación requiere --backup con un archivo SQLite nuevo.")
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        result = apply_plan(args.data_dir, plan, args.backup)
        print(json.dumps(result, ensure_ascii=False))
        return
    rows = read_rows(args.data_dir, collections, args.source_id, file_kind=args.kind)
    inventory = {
        "sources": len(rows),
        "pages": sum(max(1, len(p)) if args.kind == "images" else len(p) for _, p in rows),
        "candidate_pages": sum(
            1 if args.kind == "images" and not pages else sum(is_candidate(pg) for pg in pages)
            for _, pages in rows
        ),
        "states": dict(Counter(s["extraction_status"] for s, _ in rows)),
    }
    print(json.dumps(inventory, ensure_ascii=False), flush=True)
    if args.command == "inventory":
        return
    plan = {
        "plan_version": PLAN_VERSION,
        "data_dir": str(args.data_dir.resolve()),
        "collections": collections,
        "file_kind": args.kind,
        "created_at": now(),
        "status": "preparing",
        "inventory": inventory,
        "sources": [],
        "source_errors": [],
    }
    if args.resume and args.plan.exists():
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if (
            plan["data_dir"] != str(args.data_dir.resolve())
            or set(plan["collections"]) != set(collections)
            or plan.get("file_kind", "pdf") != args.kind
        ):
            raise DomainError("La propuesta anterior corresponde a otro alcance.")
    elif args.plan.exists():
        raise DomainError("La propuesta ya existe. Usa --resume o una ruta nueva.")
    done = {entry["source_id"]: entry for entry in plan["sources"]}
    started, processed = time.monotonic(), 0

    def progress(sid, event):
        nonlocal processed
        processed += 1
        if processed % 10 == 0:
            print(
                json.dumps(
                    {
                        "ocr_pages": processed,
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                        "source_id": sid,
                        "page": event["page"],
                        "action": event["action"],
                    }
                ),
                flush=True,
            )

    with WindowsOCR(args.language) as ocr:
        plan["engine"] = ocr.probe()
        print(json.dumps(plan["engine"], ensure_ascii=False), flush=True)
        for source, pages in rows:
            previous = done.get(source["id"])
            if previous:
                if previous["expected_state_sha256"] != state_digest(source, pages):
                    raise DomainError("Una fuente procesada cambió; usa una propuesta nueva.")
                continue
            try:
                entry = prepare_source(args.data_dir, source, pages, ocr, progress=progress)
                plan["sources"].append(entry)
            except (DomainError, OSError, RuntimeError) as exc:
                plan["source_errors"].append({"source_id": source["id"], "error": str(exc)})
            save_plan(args.plan, plan)
        plan["status"] = "prepared"
        plan["finished_at"] = now()
        save_plan(args.plan, plan)
    print(
        json.dumps(
            {
                "plan": str(args.plan),
                "prepared_sources": len(plan["sources"]),
                "changed_sources": sum(e["changed"] for e in plan["sources"]),
                "source_errors": len(plan["source_errors"]),
                "elapsed_seconds": round(time.monotonic() - started, 1),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
