"""Reproduce un benchmark privado sin escribir expedientes ni llamar a un LLM.

Entradas explícitas: caso confirmado, chunks autorizables, colecciones y referencia
independiente con checks (pasaje, IDs equivalentes y solicitud). Los documentos
reales y los resultados deben conservarse fuera de Git, por ejemplo en output/qa.
"""

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

from pqrs_claro.source_context import build_source_requests
from pqrs_claro.source_retrieval import RetrievalIndex, retrieve
from pqrs_claro.source_semantic import SemanticIndex


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalized(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("case", "chunks", "scope", "reference", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--semantic-cache", type=Path)
    parser.add_argument("--requests", nargs="*")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    case, chunks, scope, reference = [read(getattr(args, key))
                                      for key in ("case", "chunks", "scope", "reference")]
    requests = build_source_requests(case, allowed_collection_ids=scope)
    lexical = RetrievalIndex(chunks)
    semantic = SemanticIndex(args.semantic_cache) if args.semantic_cache else None
    results = {"case_id": case["id"], "llm_calls": 0, "rows": [], "checks": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for request in requests:
        if args.requests and request["id"] not in args.requests:
            continue
        started = time.monotonic()
        found = retrieve(request, chunks, index=lexical, semantic=semantic)
        row = {"request": request, "candidates": found,
               "seconds": round(time.monotonic() - started, 3)}
        results["rows"].append(row)
        for expected in reference["checks"]:
            if expected["request_id"] != request["id"]:
                continue
            hits = [c["chunk_id"] for c in found
                    if c["source_id"] in expected["accepted_source_ids"]
                    and normalized(expected["quote"]) in normalized(c["quote"])]
            results["checks"].append({**expected, "new_hits": hits})
        print(json.dumps({"request_id":request["id"], "seconds":row["seconds"],
                          "candidates":len(found)}, ensure_ascii=False), flush=True)
        args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    results["summary"] = {
        "expected_pairs":len(results["checks"]),
        "previously_found":sum(bool(c["passage_hits"]) for c in results["checks"]),
        "now_found":sum(bool(c["new_hits"]) for c in results["checks"]),
        "lost": [{"request_id":c["request_id"], "relation":c["relation"],
                  "citation_index":c["citation_index"]} for c in results["checks"]
                 if c["passage_hits"] and not c["new_hits"]],
        "semantic_warning": semantic.warning if semantic else None,
        "semantic": semantic.diagnostics if semantic else None,
    }
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(results["summary"],ensure_ascii=False),flush=True)
    if results["summary"]["lost"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
