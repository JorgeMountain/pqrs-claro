"""Verifica el mapa real del ejemplo guardado, sin lanzar nuevas llamadas a IA."""

import argparse
import json
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("case_id")
parser.add_argument("--url", default="http://127.0.0.1:8772")
args = parser.parse_args()

with httpx.Client(base_url=args.url, timeout=30) as client:
    response = client.get(f"/api/cases/{args.case_id}")
    response.raise_for_status()
    case = response.json()
    assert "ejemplo ficticio" in case["filename"].casefold(), "Solo admite el ejemplo"
    response = client.get(f"/api/cases/{args.case_id}/sources")
    response.raise_for_status()
    mapping = response.json()
    assert mapping["status"] == "ready" and not mapping["stale"], mapping["status"]
    assert len(mapping["results"]) == 3
    findings = {item["request_id"]: item for item in mapping["results"]}
    assert any(s["role"] == "rule" for s in findings["P1"]["supports"])
    assert any(s["role"] == "fact" for s in findings["P2"]["supports"])
    assert findings["P3"]["status"] in {"needs_evidence", "no_matches"}
    assert any(m["kind"] == "document" for m in findings["P3"]["missing"])
    assert not any(s["role"] == "document" for s in findings["P3"]["supports"])
    checked = 0
    for finding in mapping["results"]:
        for support in finding["supports"]:
            response = client.get(
                f"/api/sources/{support['source_id']}", params={"case_id": args.case_id}
            )
            response.raise_for_status()
            detail = response.json()
            lines = detail["pages"][support["page"] - 1]["text"].splitlines()
            quote = "\n".join(lines[support["line_start"] - 1 : support["line_end"]])
            assert quote == support["quote"]
            assert detail["source"]["version"] == support["version"]
            assert support["case_id"] == args.case_id
            assert support["category"] != "previous_response"
            checked += 1
    report = {
        "case_id": args.case_id,
        "checked_quotes": checked,
        "identification_version": case["version"],
        "mapping": mapping,
    }
    output = Path(__file__).resolve().parents[1] / "output" / "qa" / "live-sources.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "passed",
                "requests": 3,
                "exact_quotes": checked,
                "acta_missing": True,
                "evidence": str(output),
            },
            ensure_ascii=False,
        )
    )
