"""Read-only Stage3E/C2 delivery checks; never calls a scientific workflow."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

E_COMMIT = "d7eda982a91084a3b875e351de1e91dae0e5cacf"
C2_COMMIT = "f33e38a8d28bf3206989794240cc35e63d62f017"
D_COMMIT = "551f1fc38478e828e3640916fd2d7e709c7247e3"
REPOSITORY = "jiangsunyu7-ux/Wastewater_Paper"

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def immutable_url(commit, path):
    return f"https://github.com/{REPOSITORY}/raw/{commit}/{path}"

def git_check(root, commit, rel):
    disk = (root / rel).read_bytes()
    committed = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=root,
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    assert disk == committed, f"Disk/immutable commit mismatch: {rel}"
    return {"path": rel, "bytes": len(disk), "sha256": sha(disk),
            "commit": commit, "disk_equals_local_git_commit_blob": True,
            "immutable_url": immutable_url(commit, rel),
            "remote_HTTP_download_retested_this_stage": False}

def check_archive(root, rel, expected_sha, expected_bytes, members):
    path = root / rel
    assert path.stat().st_size == expected_bytes, rel
    assert sha(path.read_bytes()) == expected_sha, rel
    expected = members if isinstance(members, dict) else {a["path"]: a["sha256"] for a in members}
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None, f"CRC failed: {rel}"
        assert len(archive.namelist()) == len(set(archive.namelist())), rel
        assert set(archive.namelist()) == set(expected), rel
        for name, expected_member_sha in expected.items():
            assert sha(archive.read(name)) == expected_member_sha, f"{rel}:{name}"
    return {"path": rel, "bytes": expected_bytes, "sha256": expected_sha,
            "members_verified": len(expected), "CRC_and_all_member_SHA256": "PASSED",
            "under_24_MiB": expected_bytes < 24 * 1024 * 1024}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    out = args.output or root / "reports/stage3f_evidence_gate_v1/delivery_chain/DELIVERY_CHAIN_CHECK.json"
    start = time.perf_counter()
    e_dir = Path("delivery/20261013_stage3e")
    index = read_json(root / e_dir / "ARTIFACT_INDEX.json")
    full_checks = read_json(root / e_dir / "PACKAGE_CHECKS.json")
    originals = []
    for name in ("ARTIFACT_INDEX.json", "PACKAGE_CHECKS.json", "POST_PACKAGE_PRESERVATION.json",
                 "C2_ORIGINAL_PART01_PART02.json", "CODE_VERSION.json", "RUN_STATUS.json",
                 "SHA256SUMS", "REPRODUCE.md", "PACKAGING_RECOVERY.json"):
        originals.append(git_check(root, E_COMMIT, str(e_dir / name)))
    for command in full_checks["clean_replay"]["commands"]:
        log = Path(command["log_path"]).relative_to(root)
        checked_log = git_check(root, E_COMMIT, str(log))
        assert checked_log["sha256"] == command["log_sha256"]
        originals.append(checked_log)
    packages = []
    for record in index["packages"]:
        matching_checks = [a for a in full_checks["packages"] if a["file"] == record["file"]]
        assert len(matching_checks) == 1
        assert matching_checks[0]["sha256"] == record["sha256"]
        assert matching_checks[0]["members"] == record["members"]
        rel = str(e_dir / record["file"])
        checked = check_archive(root, rel, record["sha256"], record["bytes"], record["members"])
        checked.update(git_check(root, E_COMMIT, rel))
        checked["origin"] = "Stage3E original new package"
        packages.append(checked)
    c2_parts = []
    for record in index["original_C2_parts"]:
        rel = str(e_dir / record["file"])
        checked = check_archive(root, rel, record["sha256"], record["bytes"], record["members"])
        checked.update(git_check(root, E_COMMIT, rel))
        original_rel = str(Path("delivery/20261012_stage3c2") / record["original_file"])
        original = git_check(root, C2_COMMIT, original_rel)
        assert checked["sha256"] == original["sha256"]
        assert (root / rel).read_bytes() == (root / original_rel).read_bytes()
        checked["original_container"] = original
        checked["original_and_reissued_bytes_equal"] = True
        checked["no_original_container_regenerated"] = True
        c2_parts.append(checked)
    code = read_json(root / "reports/stage3e_evidence_review_v1/CODE_VERSION.json")
    code_archive = root / e_dir / "Wessex_Stage3E_Code_and_Reproduce_20261013.zip"
    content_version = []
    with zipfile.ZipFile(code_archive) as archive:
        for rel, expected in code["files_sha256"].items():
            assert sha((root / rel).read_bytes()) == expected, rel
            assert sha(archive.read(rel)) == expected, rel
            content_version.append({"path": rel, "sha256": expected,
                "delivery_commit": E_COMMIT,
                "committed_container": str(e_dir / code_archive.name),
                "member_path": rel,
                "individual_file_tracked_by_base_HEAD": False,
                "disk_equals_committed_container_member": True})
    helper = read_json(root / "reports/stage3e_evidence_review_v1/PACKAGING_HELPER_CHECK.json")
    assert "controlled" in helper["scope"]
    result = {"status": "PASSED", "stage": "Stage3F", "version": "stage3f_evidence_gate_v1",
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "work_scope": "Read-only original container/CRC/member/content/commit audit; no science replay",
        "actual_Stage3E_packages_verified": packages, "actual_original_C2_parts_verified": c2_parts,
        "original_receipts_verified_against_immutable_commit": originals,
        "code_content_and_true_delivery_commit": content_version,
        "base_checkout_HEAD_not_complete_code_version": code["checkout_HEAD"],
        "PACKAGING_HELPER_CHECK_scope": helper["scope"],
        "PACKAGING_HELPER_CHECK_is_actual_all_package_receipt": False,
        "actual_package_receipt": str(e_dir / "PACKAGE_CHECKS.json"),
        "previous_actual_package_clean_replay_record": full_checks["clean_replay"],
        "previous_clean_replay_not_rerun_in_Stage3F": True,
        "external_reviewer_original_containers_received_locally": False,
        "external_duplicate_parenthesis_1_and_reviewer_ZIP_not_present": True,
        "external_reviewer_reference_counts_used_as_program_pass_criteria": False,
        "new_model_training_or_scientific_result_recomputation": False,
        "seconds": time.perf_counter() - start,
        "verifier_sha256": sha(Path(__file__).read_bytes())}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "Stage3E_packages": len(packages),
        "C2_original_parts": len(c2_parts), "members_verified": sum(a["members_verified"] for a in packages+c2_parts),
        "seconds": result["seconds"], "output": str(out)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
