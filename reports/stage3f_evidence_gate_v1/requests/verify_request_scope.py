"""Check request-list integrity only; this does not verify real facility identities."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "REQUEST_INPUT_SHA256.json").read_text())
    for row in manifest["sources"]:
        assert sha256(root / row["local_copy"]) == row["sha256"], row["source_path"]
    pools = json.loads((root / "input_evidence/source_pool_definition.json").read_text())
    k30 = [p for p in pools["pools"] if p["k"] == 30]
    sources = {s for pool in k30 for s in pool["site_ids"]}
    development = set(pools["development_ids"])
    assert not (sources & development), "existing frozen SiteID partitions overlap"
    requested = sources | development
    candidate_edges = read_rows(root / "input_evidence/association_edges.csv")
    for edge in candidate_edges:
        endpoints = {edge["site_id_a"], edge["site_id_b"]}
        if endpoints & requested:
            requested |= endpoints
    rows = read_rows(root / "FACILITY_GROUPS_TEMPLATE.csv")
    assert len(rows) == len({r["SiteID"] for r in rows}), "duplicate template IDs"
    assert {r["SiteID"] for r in rows} == requested, "request list differs from frozen scope"
    prefilled = {r["SiteID"]: r for r in read_rows(root / "input_evidence/FACILITY_MAPPING_STATUS.csv")}
    for row in rows:
        assert row["published_name_for_reference_only"] == prefilled[row["SiteID"]]["provider_name_pre2022"]
        assert row["stable_physical_facility_group_id"] == "", "unreceived grouping response was prefilled"
        assert row["normal_treated_effluent_measurement_role"] == "", "unreceived role was prefilled"
    gates = read_rows(root / "EVIDENCE_GATES.csv")
    assert {"A_retrospective", "B_realtime", "C_engineering_history"} <= {g["claim_class"] for g in gates}
    assert all(g["permits_new_performance_now"] == "False" for g in gates)
    assert all(g["gate_satisfied_within_stated_scope"] == "False" for g in gates if g["claim_class"] == "B_realtime")
    result = {"status": "VERIFIED_REQUEST_SCOPE_ONLY", "unique_source_ids": len(sources),
              "development_ids": len(development), "candidate_associated_extra_ids": sorted(requested - sources - development, key=int),
              "request_ids": len(rows), "gate_rows": len(gates), "actual_physical_mapping_verified": False,
              "actual_real_time_verified": False, "new_prediction_performance_computed": False,
              "verification_code_sha256": sha256(Path(__file__))}
    (root / "REQUEST_SCOPE_CHECK.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
