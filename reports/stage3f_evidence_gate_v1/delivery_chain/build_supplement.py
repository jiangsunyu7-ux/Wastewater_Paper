"""Package original Stage3E receipts plus immutable C2/D dependency addresses."""
from __future__ import annotations
import csv
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from verify_delivery_chain import C2_COMMIT, D_COMMIT, E_COMMIT, git_check, immutable_url, read_json, sha

ROOT = Path(__file__).resolve().parents[3]
CHAIN = ROOT / "reports/stage3f_evidence_gate_v1/delivery_chain"
DELIVERY = ROOT / "delivery/20261013_stage3f"

def csv_file(path, rows, columns):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

def original_copy(rel, destination, commit=None):
    source = ROOT / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    assert sha(destination.read_bytes()) == sha(source.read_bytes())
    row = {"original_path": rel, "supplement_member": str(destination.relative_to(CHAIN)),
           "bytes": source.stat().st_size, "sha256": sha(source.read_bytes()),
           "original_bytes_preserved": True, "commit": commit}
    if commit:
        verified = git_check(ROOT, commit, rel)
        row["immutable_url"] = verified["immutable_url"]
    return row

def main():
    check = read_json(CHAIN / "DELIVERY_CHAIN_CHECK.json")
    assert check["status"] == "PASSED"
    copied = []
    for original in check["original_receipts_verified_against_immutable_commit"]:
        rel = original["path"]
        suffix = Path(rel).relative_to("delivery/20261013_stage3e")
        copied.append(original_copy(rel, CHAIN / "original_stage3e_receipts" / suffix, E_COMMIT))
    for rel, name, commit in [
        ("configs/stage3c2_source_scale_v1/FREEZE.json", "STAGE3C2_FREEZE.json", None),
        ("configs/stage3c2_source_scale_v1/full.json", "STAGE3C2_full.json", None),
        ("delivery/20261012_stage3c2/REPRODUCE.md", "STAGE3C2_REPRODUCE.md", C2_COMMIT),
        ("delivery/20261012_stage3c2/README.md", "STAGE3C2_ORIGINAL_README.md", C2_COMMIT),
        ("delivery/20261012_stage3c2/PACKAGE_CHECKS.json", "STAGE3C2_PACKAGE_CHECKS.json", C2_COMMIT),
        ("reports/stage3e_evidence_review_v1/results/INPUT_MANIFEST.json", "STAGE3E_original_D_INPUT_MANIFEST.json", None),
    ]:
        copied.append(original_copy(rel, CHAIN / "original_dependencies" / name, commit))
    (CHAIN / "ORIGINAL_COPIES.json").write_text(json.dumps(copied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dependencies = []
    for original in check["original_receipts_verified_against_immutable_commit"]:
        dependencies.append({"stage": "Stage3E receipt", "role": "Original delivery receipt or original clean-replay log",
            "file": Path(original["path"]).name, "bytes": original["bytes"], "sha256": original["sha256"],
            "commit": E_COMMIT, "immutable_url": original["immutable_url"],
            "verified_scope_Stage3F": "Current original file equals locally available immutable Git blob; no replay"})
    for original in check["actual_Stage3E_packages_verified"]:
        dependencies.append({"stage": "Stage3E", "role": "Previously completed original new Stage3E package",
            "file": Path(original["path"]).name, "bytes": original["bytes"], "sha256": original["sha256"],
            "commit": E_COMMIT, "immutable_url": original["immutable_url"],
            "verified_scope_Stage3F": "Local original container SHA/CRC/all member SHA plus immutable local Git blob"})
    c2_checks = read_json(ROOT / "delivery/20261012_stage3c2/PACKAGE_CHECKS.json")
    c2_part_names = {a["original_container"]["path"] for a in check["actual_original_C2_parts_verified"]}
    for row in c2_checks["packages"]:
        rel = str(Path("delivery/20261012_stage3c2") / row["file"])
        original = git_check(ROOT, C2_COMMIT, rel)
        assert original["sha256"] == row["sha256"] and original["bytes"] == row["bytes"]
        dependencies.append({"stage": "Stage3C2 ORIGINAL", "role": row["category"],
            "file": row["file"], "bytes": row["bytes"], "sha256": row["sha256"],
            "commit": C2_COMMIT, "immutable_url": immutable_url(C2_COMMIT, rel),
            "verified_scope_Stage3F": "Local original SHA/CRC/all member SHA and immutable local Git blob" if rel in c2_part_names else "Local original container SHA and immutable local Git blob; original full checks copied unchanged"})
    for row in check["actual_original_C2_parts_verified"]:
        dependencies.append({"stage": "Stage3C2 ORIGINAL SAME-BYTE REISSUE", "role": "Optional alternate download of exactly the original container bytes",
            "file": Path(row["path"]).name, "bytes": row["bytes"], "sha256": row["sha256"],
            "commit": E_COMMIT, "immutable_url": row["immutable_url"],
            "verified_scope_Stage3F": "Byte-exact original C2 container equality, local CRC and all member SHA; not regenerated"})
    d_checks = read_json(ROOT / "delivery/20261012_stage3d/PACKAGE_CHECKS.json")
    for row in d_checks["packages"]:
        rel = str(Path("delivery/20261012_stage3d") / row["file"])
        dependencies.append({"stage": "Stage3D dependency", "role": row["category"],
            "file": row["file"], "bytes": row["bytes"], "sha256": row["sha256"],
            "commit": D_COMMIT, "immutable_url": immutable_url(D_COMMIT, rel),
            "verified_scope_Stage3F": "Address/hash copied from original delivery receipt; D containers/science not replayed in F"})
    csv_file(CHAIN / "IMMUTABLE_DOWNLOADS.csv", dependencies,
        ["stage", "role", "file", "bytes", "sha256", "commit", "immutable_url", "verified_scope_Stage3F"])
    inputs = read_json(ROOT / "reports/stage3e_evidence_review_v1/results/INPUT_MANIFEST.json")
    input_rows = [{"original_path": rel, "bytes": (ROOT/rel).stat().st_size,
        "sha256": value, "required_for": "Full Stage3E diagnostics from original D evidence; not recomputed in F"}
        for rel, value in inputs["inputs_sha256"].items()]
    csv_file(CHAIN / "STAGE3E_FILE_DEPENDENCIES.csv", input_rows,
             ["original_path", "bytes", "sha256", "required_for"])
    versions = list(check["code_content_and_true_delivery_commit"])
    c2_code_path = "delivery/20261012_stage3c2/Wastewater_Stage3C2_Code_and_Reproduce_20261012.zip"
    c2_code_receipt = git_check(ROOT, C2_COMMIT, c2_code_path)
    with zipfile.ZipFile(ROOT / c2_code_path) as archive:
        for rel, expected in read_json(ROOT / "configs/stage3c2_source_scale_v1/FREEZE.json")["files_sha256"].items():
            assert sha(archive.read(rel)) == expected
            assert sha((ROOT / rel).read_bytes()) == expected
            versions.append({"path": rel, "sha256": expected, "delivery_commit": C2_COMMIT,
                "committed_container": c2_code_path, "member_path": rel,
                "individual_file_tracked_by_base_HEAD": False,
                "disk_equals_committed_container_member": True})
    (CHAIN / "CODE_CONTENT_AND_COMMIT.json").write_text(json.dumps({
        "base_HEAD_is_not_a_complete_scientific_code_version": True,
        "version_rule": "Content SHA256 + real delivery Git commit + committed code ZIP + exact member path",
        "Stage3E_delivery_commit": E_COMMIT, "Stage3C2_delivery_commit": C2_COMMIT,
        "C2_code_container": c2_code_receipt, "files": versions}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    csv_file(CHAIN / "ORIGINAL_C2_MISSING_EXTERNAL_PARTS.csv", [
        {"original_file": a["original_container"]["path"].split("/")[-1], "bytes": a["bytes"],
         "sha256": a["sha256"], "immutable_original_url": a["original_container"]["immutable_url"],
         "same_byte_reissue_url": a["immutable_url"], "external_reviewer_received_at_start": "not_received (user report)",
         "Stage3F_local_original_verified": True} for a in check["actual_original_C2_parts_verified"]],
         ["original_file", "bytes", "sha256", "immutable_original_url", "same_byte_reissue_url", "external_reviewer_received_at_start", "Stage3F_local_original_verified"])
    members = {str(p.relative_to(CHAIN)): sha(p.read_bytes()) for p in sorted(CHAIN.rglob("*"))
               if p.is_file() and str(p.relative_to(CHAIN)) not in ("SUPPLEMENT_MANIFEST.json", "SHA256SUMS")
               and "__pycache__" not in p.parts}
    (CHAIN / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name,value in members.items()), encoding="utf-8")
    manifest = {"stage": "Stage3F delivery-chain work, supplements Stage3E completed delivery",
        "version": "stage3f_evidence_gate_v1", "generated_utc": datetime.now(timezone.utc).isoformat(),
        "supplement_of_original_delivery_commit": E_COMMIT,
        "original_stage3e_scientific_results_regenerated": False,
        "old_large_containers_included": False,
        "members_sha256": members}
    (CHAIN / "SUPPLEMENT_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    package = DELIVERY / "Wessex_Stage3E_Delivery_Supplement_20261013.zip"
    if package.exists():
        raise FileExistsError("Preserve existing supplement; choose new version for a rebuild")
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(CHAIN.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, str(path.relative_to(CHAIN)))
    actual = {}
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            actual[name] = sha(archive.read(name))
            assert actual[name] == sha((CHAIN / name).read_bytes())
        for name,value in members.items():
            assert actual[name] == value
    assert package.stat().st_size < 24 * 1024 * 1024
    check_result = {"status": "PASSED", "scope": "Actual newly created supplement container and every member, not a packaging fixture",
        "file": package.name, "bytes": package.stat().st_size,
        "MiB": package.stat().st_size / (1024 * 1024), "sha256": sha(package.read_bytes()),
        "members_sha256": actual, "CRC_and_all_member_SHA256": "PASSED",
        "old_original_receipts_copied_byte_exact": True,
        "old_scientific_outputs_or_old_containers_regenerated": False,
        "checked_utc": datetime.now(timezone.utc).isoformat()}
    (DELIVERY / "STAGE3E_SUPPLEMENT_PACKAGE_CHECK.json").write_text(json.dumps(check_result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in check_result.items() if k != "members_sha256"}, ensure_ascii=False))

if __name__ == "__main__":
    main()
