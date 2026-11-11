from copy import deepcopy

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from pqrs_claro.source_graph import build_source_graph


@pytest.mark.parametrize("change", ["none", "order", "numeric_type", "line", "request", "scope",
                                    "not_authorized", "earlier_error"])
def test_raw_checkpoint_reuse_requires_identical_authorized_inputs(tmp_path, change):
    request = {"id": "P1", "case_id": "A", "title": "Inventario", "allowed_collection_ids": ["X"]}
    rows = [{"chunk_id": cid, "source_id": "fuente", "collection_id": "X", "quote": cid,
             "line_start": i} for i, cid in enumerate(("tubo", "placa"), 1)]
    if change == "not_authorized":
        rows[0]["case_id"] = "B"

    class Reader:
        calls = 0

        def assess(self, req, candidates):
            self.calls += 1
            return {"request_id": req["id"], "status": "error" if (
                self.calls == 1 and change == "earlier_error") else "references_found"}

    reader = Reader()
    first = {"configurable": {"thread_id": "A:P1:anterior"}}
    next_run = {"configurable": {"thread_id": "A:P1:actual"}}
    with SqliteSaver.from_conn_string(str(tmp_path / "source_checkpoints.sqlite")) as saver:
        graph = build_source_graph(lambda *_: rows, reader, saver)
        graph.invoke({"request": request, "chunks": []}, first)
        current, data = deepcopy(request), deepcopy(rows)
        if change == "order":
            data.reverse()
        elif change == "numeric_type":
            data[0]["line_start"] = True  # Python compares True equal to 1.
        elif change == "line":
            data[0]["quote"] += "."
        elif change == "request":
            current["title"] = "Cantidad"
        elif change == "scope":
            current["allowed_collection_ids"].append("Y")
        graph = build_source_graph(lambda *_: data, reader, saver, prior_config=first)
        graph.invoke({"request": current, "chunks": []}, next_run)
    assert reader.calls == (1 if change == "none" else 2)
