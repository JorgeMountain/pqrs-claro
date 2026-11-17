"""Replay identical injected omissions against a code snapshot, without API calls.

Uses the versioned fictional fixtures in test_request_trace_generalization.py.
Outputs are scripted model responses; this measures recovery of a known omission,
not spontaneous production-model accuracy. Prior outputs are never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def hashes(code):
    return {str(path.relative_to(code)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((code / "src/pqrs_claro").rglob("*.py"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=PROJECT / "output/qa/trace-generalization-20261117")
    args = parser.parse_args()
    code = args.code_root.resolve()
    assert (code / "src/pqrs_claro/draft_graph.py").is_file()
    assert args.label.replace("-", "").replace("_", "").isalnum()
    output = args.output_dir.resolve() / f"injected-{args.label}.json"
    assert not output.exists(), "Keep prior outputs; select a new label"
    sys.path.insert(0, str(PROJECT / "tests"))
    sys.path.insert(0, str(code / "src"))

    import test_request_trace_generalization as fixture
    from langgraph.checkpoint.memory import InMemorySaver
    from test_draft_engine import engine

    from pqrs_claro.draft_graph import build_draft_graph

    initial_hashes = hashes(code)
    rows = []
    for label, first, second in fixture.EXAMPLES:
        request, finding, plan, draft = fixture.scenario(label, first, second)
        worker, calls = engine(plan, draft, fixture.review(True), {
            "paragraphs": [], "omitted_unit_paragraphs": [
                {"unit_id": "U2", "text": second, "cited_chunk_ids": ["S1"]}]},
            fixture.review(False))
        result = build_draft_graph(worker, InMemorySaver()).invoke(
            {"request": request, "finding": finding},
            {"configurable": {"thread_id": label}})
        paragraphs = result["draft"]["paragraphs"]
        pending_before = json.loads(calls[2]["input"])["draft"]["pending"]
        rows.append({
            "domain": label, "scripted_model_calls": len(calls),
            "first_answer_unchanged": paragraphs[0]["text"] == first,
            "omitted_answer_restored": any(p["text"] == second for p in paragraphs),
            "legitimate_pending_exact": pending_before == result["draft"]["pending"],
            "no_extra_sources": all(
                p["cited_chunk_ids"] == [finding["supports"][0]["chunk_id"]]
                for p in paragraphs),
            "final_status": result["checks"]["status"], "result": result,
        })
    loaded = {
        name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
        if name.startswith("pqrs_claro") and getattr(module, "__file__", None)}
    assert all(Path(path).is_relative_to(code / "src") for path in loaded.values())
    assert initial_hashes == hashes(code), "Code changed during replay"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mode": "Injected omissions, not spontaneous LLM quality", "api_calls": 0,
               "code_root": str(code), "code_hashes": initial_hashes,
               "fixture_sha256": hashlib.sha256(Path(fixture.__file__).read_bytes()).hexdigest(),
               "loaded_modules": loaded, "rows": rows}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"label": args.label, "output": str(output), "rows": [
        {key: value for key, value in row.items() if key != "result"} for row in rows]}))


if __name__ == "__main__":
    main()
