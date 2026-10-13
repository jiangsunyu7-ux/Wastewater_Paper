#!/usr/bin/env python3
"""Check only Stage3F literature provenance, not novelty or scientific gains."""
import csv
import hashlib
import json
from pathlib import Path


def main():
    base = Path(__file__).resolve().parent
    manifest = json.loads((base / "SOURCE_MANIFEST.json").read_text())
    checked = []
    for item in manifest["sources"]:
        path = base / item["package_path"]
        blob = path.read_bytes()
        assert len(blob) == item["bytes"], item["id"]
        assert hashlib.sha256(blob).hexdigest() == item["sha256"], item["id"]
        checked.append(item["id"])
    text = (base / "evidence/L04_publisher_visible_text.txt").read_text()
    for quote in json.loads((base / "KIM_SELECTED_QUOTES.json").read_text()):
        assert quote["quote_original_ko"] in text
        assert hashlib.sha256((base / quote["source"]).read_bytes()).hexdigest() == quote["source_sha256"]
    with (base / "LITERATURE_DELTA.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert {row["record_id"] for row in rows} == {"L01", "L03", "L04"}
    status = json.loads((base / "LITERATURE_DELTA_STATUS.json").read_text())
    assert status["new_fulltexts_obtained"] == 0
    assert status["new_original_methods_obtained"] == 0
    assert status["new_performance_computed"] is False
    assert status["nearest_paper_fulltext_novelty_gate"] == "NOT_PASSED"
    logs = json.loads((base / "NEW_ACCESS_LOG.json").read_text())
    assert len(logs) == status["network_requests"] == 3
    assert sum(log.get("status") == 200 for log in logs) == 1
    preprint = json.loads((base / "wr_author_preprint_crossref.json").read_text())["message"]
    assert preprint["relation"]["is-preprint-of"][0]["id"].lower() == "10.1029/2022wr033826"
    report = {
        "status": "PASSED_PROVENANCE_ONLY",
        "sources_checked": checked,
        "delta_rows": len(rows),
        "new_full_text_or_methods_verified": False,
        "novelty_established": False,
        "physical_facilities_verified": False,
    }
    (base / "PROVENANCE_CHECK.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
