#!/usr/bin/env python3
"""Create and independently extract Stage3G evidence packages, without fitting models.

The ZIP member manifest omits only its own digest. External ARTIFACT_INDEX.json
hashes the complete ZIP, including that manifest. The final Delivery_Index ZIP
contains the index for the payload ZIPs; its own SHA is in the external final
SHA256SUMS.txt, avoiding a circular archive/self-digest claim.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
VERSION = "stage3g_transfer_reliability_v1"
MANIFEST = "PACKAGE_MEMBER_SHA256.json"
README = "PACKAGE_README.md"
MAX_BYTES = 24 * 1024 * 1024


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def git_text(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def stage_gate():
    cfg_path = ROOT / f"configs/{VERSION}/full.json"
    cfg = json.loads(cfg_path.read_text())
    freeze = json.loads((ROOT / cfg["frozen_manifest"]).read_text())
    for filename, expected in freeze["files_sha256"].items():
        if not (ROOT / filename).is_file() or sha(ROOT / filename) != expected:
            raise ValueError("Frozen file absent/changed: " + filename)
    paths = dict(
        source=ROOT / cfg["source_output"] / "SOURCE_RUN_STATUS.json",
        source_risk=ROOT / cfg["source_output"] / "reliability/RUN_STATUS.json",
        full_point=ROOT / cfg["output"] / "RUN_STATUS.json",
        full_risk=ROOT / cfg["output"] / "reliability/RUN_STATUS.json",
        evaluation=ROOT / cfg["report_output"] / "evaluation_validation.json",
        independent=ROOT / f"reports/{VERSION}/audit/INDEPENDENT_RESULTS_CHECK_FULL.json",
    )
    records = {}
    for label, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError("Final packaging requires: " + str(path.relative_to(ROOT)))
        record = json.loads(path.read_text())
        expected_status = "PASSED" if label == "independent" else "COMPLETED"
        if record.get("status") != expected_status:
            raise ValueError(f"{label} is {record.get('status')}, not {expected_status}")
        records[label] = dict(path=str(path.relative_to(ROOT)), sha256=sha(path), status=record["status"])
    point = json.loads(paths["full_point"].read_text())
    if point.get("expected") != 300 or point.get("disk_verified_completed") != 300 or point.get("not_completed"):
        raise ValueError("Full point matrix is incomplete")
    risk = json.loads(paths["full_risk"].read_text())
    if risk.get("row_counts", {}).get("target_risk_predictions.csv.gz") != 216000:
        raise ValueError("Full target risk row count differs from frozen matrix")
    independent = json.loads(paths["independent"].read_text())
    if len(independent.get("independent_primary_bootstrap_comparisons", [])) != 12:
        raise ValueError("Independent audit has not checked statistics")
    # Check every task/cache member against its original receipt rather than
    # relying only on a top-level completed flag.
    expected_jobs = {f"{site}_{origin}_B{budget}_H{horizon}" for site in cfg["development_ids"]
        for origin in cfg["evaluation_origins"] for budget in cfg["budgets"] for horizon in cfg["horizons"]}
    folders = [p for p in (ROOT / cfg["output"] / "jobs").iterdir() if p.is_dir()]
    if {p.name for p in folders} != expected_jobs:
        raise ValueError("Full task directory set differs from frozen matrix")
    for folder in sorted(folders):
        if not folder.is_dir():
            continue
        state_path = folder / "status.json"
        state = json.loads(state_path.read_text())
        if state.get("status") != "COMPLETED":
            raise ValueError("Task receipt is not completed: " + folder.name)
        hashes = state.get("files_sha256", state.get("outputs_sha256", {}))
        if not hashes:
            raise ValueError("Task receipt lacks member SHA: " + folder.name)
        expected_members = {"predictions.csv", "risk_inputs.csv", "source_weights.csv", "selection.json",
            "validation_grid.csv", "diagnostics.json", "model_parameters.npz"}
        if set(hashes) != expected_members or not state.get("write_verified"):
            raise ValueError("Task required-member set/writeback differs: " + folder.name)
        for filename, expected in hashes.items():
            if not (folder / filename).is_file() or sha(folder / filename) != expected:
                raise ValueError("Task output absent/changed: " + folder.name + "/" + filename)
    for pool in cfg["pools"]:
        folder = ROOT / cfg["source_output"] / pool["pool_id"]
        state = json.loads((folder / "status.json").read_text())
        if state.get("status") != "COMPLETED" or not state.get("write_verified"):
            raise ValueError("Source pool state incomplete: " + pool["pool_id"])
        for filename, expected in state["outputs_sha256"].items():
            if sha(folder / filename) != expected:
                raise ValueError("Source output SHA mismatch: " + filename)
    for label in ("source_risk", "full_risk"):
        record = json.loads(paths[label].read_text())
        for filename, expected in record["members"].items():
            if sha(paths[label].parent / filename) != expected:
                raise ValueError("Risk output SHA mismatch: " + filename)
    return cfg, records


def list_files(directory, suffixes=None):
    directory = ROOT / directory
    if not directory.exists():
        return []
    return [p for p in sorted(directory.rglob("*")) if p.is_file()
            and "__pycache__" not in p.parts and not p.name.endswith((".pyc", ".tmp"))
            and (suffixes is None or p.suffix in suffixes)]


def existing(paths):
    return [ROOT / p for p in paths if (ROOT / p).is_file()]


def payloads(cfg):
    reports = list_files(f"reports/{VERSION}")
    # Large source/target rows live in diagnostics parts, not Quick Review.
    quick = [p for p in reports if p.name != "FROZEN_CODE_AND_CONFIG.zip" and p.stat().st_size < 2 * 1024 * 1024
             and p.name not in {"PRESERVATION_BEFORE.json", "PRESERVATION_AFTER.json"}]
    quick += existing(["STAGE3G_PROTOCOL.md", f"configs/{VERSION}/full.json", f"configs/{VERSION}/FREEZE.json"])
    quick += list_files(f"figures/{VERSION}")
    code_modules = ["__init__", "common", "shared_data", "stage3a_data", "stage3b_models", "stage3b_experiment",
                    "stage3c2_source", "stage3c2_evaluation", "stage3d_experiment", "stage3d_intervals", "stage3e_runtime",
                    "stage3g_core", "stage3g_source", "stage3g_experiment", "stage3g_reliability", "stage3g_evaluation"]
    code = existing([f"src/wastewater/{name}.py" for name in code_modules])
    code += existing(["AGENTS.md", "STAGE3G_PROTOCOL.md", "requirements-stage3g.txt",
        "scripts/check_stage3g_results.py", "scripts/run_stage3g_reliability.py", "scripts/summarize_stage3g.py",
        "scripts/plot_stage3g.py", "scripts/package_stage3g.py", "scripts/measure_stage3g.py", "notebooks/Stage3GCPU.ipynb",
        f"reports/{VERSION}/REPRODUCE.md", f"reports/{VERSION}/CODE_VERSION.json",
        f"reports/{VERSION}/INPUT_DEPENDENCIES.json", f"reports/{VERSION}/PACKAGE_CONTENT_VERSION.json", f"reports/{VERSION}/FROZEN_CODE_AND_CONFIG.zip",
        "materials/received_stage2_20261009/paper idea.docx",
        cfg["canonical_csv"], "data/derived/stage3c2_source_scale_v1/manifest.json", cfg["source_pool_definition"], cfg["partition_group_ledger"]])
    code += list_files(f"configs/{VERSION}")
    code += [p for p in list_files("tests") if p.name.startswith("test_stage3g")]
    code += existing(["data/provenance/stage3c2_source_scale_v1/DATA_VERIFICATION.json",
        "data/provenance/stage3c2_source_scale_v1/CLEAN_INPUT_REPLAY.json",
        "data/provenance/stage3c2_source_scale_v1/COHORT_AND_INPUT_NOTES_ZH.md",
        "data/provenance/stage3c2_source_scale_v1/association_edges.csv",
        "data/provenance/stage3c2_source_scale_v1/nested_source_pool_members.csv",
        "data/provenance/stage3c2_source_scale_v1/source_measurement_use_ledger.csv",
        "data/provenance/stage3c2_source_scale_v1/temporary_and_registered_protection.csv"])
    diagnostics = list_files(f"runs/{VERSION}")
    diagnostics += [p for p in reports if p not in quick and p.name != "FROZEN_CODE_AND_CONFIG.zip"]
    diagnostics += [p for p in list_files("validation") if p.name.startswith("stage3g_")]
    # No old archive or full old-stage predictions are included.
    return {"Quick_Review": sorted(set(quick)), "Code_and_Reproduce": sorted(set(code)),
            "Predictions_and_Diagnostics": sorted(set(diagnostics))}


def write_archive(path, files, label, snapshot, scientific_status="COMPLETED"):
    if path.exists():
        raise FileExistsError("Never overwrite a delivered archive: " + str(path))
    readme = (f"# Wessex Stage3G — {label}\n\nVersion: {VERSION}\n"
        "This is a new bounded development experiment, not an independent final test.\n"
        "Extract all parts into one new directory, preserving the repository-relative paths.\n"
        "Old Stage3C2/3D scientific archives are not renamed or regenerated.\n"
        "The per-member manifest excludes its own digest; the external index hashes the complete ZIP.\n"
        "For CPU reproduction see reports/stage3g_transfer_reliability_v1/REPRODUCE.md.\n").encode()
    member_hashes = {str(p.relative_to(ROOT)): snapshot[str(p.relative_to(ROOT))] for p in files}
    member_hashes[README] = dict(bytes=len(readme), sha256=hashlib.sha256(readme).hexdigest())
    manifest = dict(stage="Stage3G", version=VERSION, package_role=label,
        generated_utc=now(), execution_and_output_validation_status=scientific_status, members=member_hashes,
        manifest_self_hash_omitted=True, external_zip_sha_covers_manifest=True)
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for member_count, source in enumerate(files, 1):
            if member_count == 1 or member_count % 100 == 0 or member_count == len(files):
                print(f"pack {label}: {member_count}/{len(files)} members", flush=True)
            name = str(source.relative_to(ROOT))
            if sha(source) != snapshot[name]["sha256"]:
                raise ValueError("Source changed while packaging: " + name)
            archive.write(source, name)
        archive.writestr(README, readme)
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def split_archive(output, files, label, date, snapshot, maximum, counter=None):
    counter = [0] if counter is None else counter
    # Build to a temporary filename; oversize archives are deleted and their
    # file lists split, never silently omit a negative result to shrink a ZIP.
    temporary = output / f".{label}_{counter[0]:03d}.building.zip"
    write_archive(temporary, files, label, snapshot)
    if temporary.stat().st_size >= maximum:
        temporary.unlink()
        if len(files) <= 1:
            raise ValueError("One member cannot fit below the ZIP size limit: " + str(files[0]))
        middle = len(files) // 2
        return (split_archive(output, files[:middle], label, date, snapshot, maximum, counter)
                + split_archive(output, files[middle:], label, date, snapshot, maximum, counter))
    counter[0] += 1
    name = f"Wessex_Stage3G_{label}_{date}_Part{counter[0]:02d}.zip"
    target = output / name
    if target.exists():
        raise FileExistsError(target)
    temporary.rename(target)
    return [target]


def compressed_sizes(reference_directory):
    """Read actual verified first-attempt member compression costs, not scores."""
    costs = {}
    if reference_directory:
        for archive_path in sorted(Path(reference_directory).glob("*.zip")):
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    if info.filename not in {MANIFEST, README}:
                        costs[info.filename] = info.compress_size
    return costs


def member_compressed_size(source):
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    size = 0
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(compressor.compress(chunk))
    return size + len(compressor.flush())


def planned_archive_groups(files, maximum, costs):
    """Deterministic first-fit-decreasing by actual byte cost, no data omission."""
    weighted = []
    for source in files:
        name = str(source.relative_to(ROOT))
        # Conservatively budget ZIP headers, UTF-8 names, and the member's
        # digest record; actual final archive size is still checked afterward.
        cost = costs.get(name)
        if cost is None:
            cost = member_compressed_size(source)
        weighted.append((int(cost) + 76 + 2 * len(name.encode()) + 600, name, source))
    weighted.sort(key=lambda row: (-row[0], row[1]))
    bins = []
    capacity = maximum - 65536
    for cost, name, source in weighted:
        if cost >= capacity:
            raise ValueError("Member cannot fit below requested ZIP limit: " + name)
        for item in bins:
            if item["cost"] + cost < capacity:
                item["files"].append(source); item["cost"] += cost
                break
        else:
            bins.append(dict(cost=cost, files=[source]))
    return [sorted(item["files"]) for item in bins]

def verify_archive(path, extract_root):
    path = Path(path)
    extract = Path(extract_root) / path.stem
    extract.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive member")
        for info in archive.infolist():
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Unsafe member: " + info.filename)
        bad = archive.testzip()
        if bad is not None:
            raise ValueError("CRC failed: " + bad)
        manifest = json.loads(archive.read(MANIFEST))
        if set(names) != set(manifest["members"]) | {MANIFEST}:
            raise ValueError("Manifest/member set differs")
        archive.extractall(extract)
    records = {}
    for member_count, (name, expected) in enumerate(manifest["members"].items(), 1):
        if member_count == 1 or member_count % 100 == 0 or member_count == len(manifest["members"]):
            print(f"extract/check {path.name}: {member_count}/{len(manifest["members"])}", flush=True)
        target = extract / name
        actual = dict(bytes=target.stat().st_size, sha256=sha(target))
        if actual != expected:
            raise ValueError("Extracted member mismatch: " + name)
        records[name] = actual
    return dict(package=path.name, bytes=path.stat().st_size, sha256=sha(path), crc_passed=True,
        member_sha_passed=True, safe_independent_extraction=True, payload_members=len(records),
        member_manifest_self_digest_omitted=True, extraction_directory=str(extract), members=records)


def actual_code_version(code_paths, scientific_commit=None):
    paths = [p for p in code_paths if p.suffix == ".py" or p.suffix == ".ipynb" or p.name.endswith(".json") and "configs" in p.parts]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    content_digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    tracked = set(git_text("ls-files").splitlines())
    return dict(recorded_utc=now(), actual_checkout_commit=git_text("rev-parse", "HEAD"),
        actual_checkout_branch=git_text("branch", "--show-current"),
        scientific_content_commit=scientific_commit, scientific_content_sha256=content_digest,
        code_files_sha256=hashes,
        untracked_scientific_members=[name for name in hashes if name not in tracked],
        checkout_HEAD_is_not_a_complete_scientific_content_version=any(name not in tracked for name in hashes),
        content_SHA_and_frozen_originals_are_authoritative=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("build", help="Refuse partial science; create and extract-check genuine new packages")
    create.add_argument("--output", default="delivery/20261014_stage3g")
    create.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    create.add_argument("--max-mib", type=float, default=24)
    create.add_argument("--extract-root")
    create.add_argument("--scientific-commit")
    create.add_argument("--compressed-reference", help="Optional completed first-attempt ZIP directory for exact member compression costs")
    verify = sub.add_parser("verify", help="Independently CRC/extract/member-SHA check supplied actual packages")
    verify.add_argument("archives", nargs="+")
    verify.add_argument("--extract-root", required=True)
    args = parser.parse_args()
    if args.action == "verify":
        checks = [verify_archive(Path(path), args.extract_root) for path in args.archives]
        print(json.dumps(dict(status="PASSED", packages=checks), indent=2))
        return
    cfg, gates = stage_gate()
    # This supplementary index repairs only missing display metadata. Original
    # diagnostics files and their original SHA remain untouched.
    rows = []
    for folder in sorted((ROOT / cfg["output"] / "jobs").iterdir()):
        if not folder.is_dir():
            continue
        diag_path = folder / "diagnostics.json"
        original = json.loads(diag_path.read_text())
        with (folder / "predictions.csv").open() as stream:
            ids = {row["site_id"] for row in csv.DictReader(stream)}
        if len(ids) != 1 or next(iter(ids)) != folder.name.split("_")[0]:
            raise ValueError("Task name/actual prediction SiteID mismatch: " + folder.name)
        actual_site = next(iter(ids))
        rows.append(dict(task=folder.name, site_id=actual_site,
            original_diagnostics_site_id=original.get("site_id"),
            site_id_source="verified task name and predictions.csv unique site_id",
            original_diagnostics_path=str(diag_path.relative_to(ROOT)),
            original_diagnostics_sha256=sha(diag_path),
            initial_budget_start=original.get("budget_start"), fit_end=original.get("fit_end"),
            training_samples=original.get("training_labels", original.get("fitting_labels")),
            missing_original_site_id=original.get("site_id") is None))
    index_path = ROOT / f"reports/{VERSION}/TRAINING_DIAGNOSTIC_INDEX.csv"
    with index_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError("Delivery directory must be empty, so old packages cannot be overwritten")
    report = ROOT / f"reports/{VERSION}"
    groups = payloads(cfg)
    if not (report / "CODE_VERSION.json").is_file():
        raise FileNotFoundError("Root scientific CODE_VERSION.json must exist before final packaging")
    write_json(report / "PACKAGE_CONTENT_VERSION.json", actual_code_version(groups["Code_and_Reproduce"], args.scientific_commit))
    groups = payloads(cfg)
    all_files = sorted(set(p for files in groups.values() for p in files))
    snapshot = {str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in all_files}
    archives = []
    compressed_reference = compressed_sizes(args.compressed_reference)
    for label, files in groups.items():
        if not files:
            raise ValueError("Empty package category: " + label)
        planned = planned_archive_groups(files, int(args.max_mib * 1024 * 1024), compressed_reference)
        print(f"planned {label}: {len(files)} preserved members in {len(planned)} byte-balanced archives", flush=True)
        counter = [0]
        for group in planned:
            archives += split_archive(output, group, label, args.date, snapshot, int(args.max_mib * 1024 * 1024), counter)
    extract_root = Path(args.extract_root) if args.extract_root else Path(tempfile.mkdtemp(prefix="stage3g-package-extract-"))
    checks = [verify_archive(path, extract_root) for path in archives]
    if any(record["bytes"] >= args.max_mib * 1024 * 1024 for record in checks):
        raise ValueError("Package exceeds requested maximum")
    for filename, expected in snapshot.items():
        if sha(ROOT / filename) != expected["sha256"]:
            raise ValueError("Source changed after packaging: " + filename)
    write_json(output / "PACKAGE_CHECKS.json", dict(stage="Stage3G", version=VERSION,
        status="PASSED", checked_utc=now(), actual_payload_packages=checks,
        not_a_packaging_fixture=True, extracted_member_records=sum(c["payload_members"] for c in checks)))
    index = dict(stage="Stage3G", version=VERSION, generated_utc=now(), actual_completion="COMPLETED",
        result_directory=cfg["output"], source_directory=cfg["source_output"], report_directory=cfg["report_output"],
        code_version=json.loads((report / "CODE_VERSION.json").read_text()),
        package_support_version=json.loads((report / "PACKAGE_CONTENT_VERSION.json").read_text()),
        config=dict(path=f"configs/{VERSION}/full.json", sha256=sha(ROOT / f"configs/{VERSION}/full.json")),
        completion_evidence=gates, package_limit_bytes=int(args.max_mib * 1024 * 1024),
        payload_packages=[{key: record[key] for key in ("package", "bytes", "sha256", "payload_members")} for record in checks],
        package_checks_sha256=sha(output / "PACKAGE_CHECKS.json"),
        index_package_is_separate_and_its_own_SHA_is_external_to_avoid_circular_self_hash=True,
        old_stage_archives_not_renamed_or_regenerated=True)
    write_json(output / "ARTIFACT_INDEX.json", index)
    sums = "".join(f"{sha(path)}  {path.name}\n" for path in archives)
    (output / "PAYLOAD_SHA256SUMS.txt").write_text(sums)
    (output / "DELIVERY_README.md").write_text(
        "# Stage3G delivery index\n\nAll payload ZIPs below24MiB and independently extracted/checked.\n"
        "Extract Code_and_Reproduce and all Predictions_and_Diagnostics parts into one directory before running reproduction commands.\n"
        "Quick_Review is the summary; it is not alone a full reproduction.\n"
        "ARTIFACT_INDEX.json hashes payload ZIPs; PACKAGE_CHECKS.json records actual CRC and extracted member SHA checks.\n"
        "The index ZIP's own digest is external in SHA256SUMS.txt, avoiding circular claims.\n")
    index_archive = output / f"Wessex_Stage3G_Delivery_Index_{args.date}.zip"
    index_paths = [output / name for name in ("ARTIFACT_INDEX.json", "PACKAGE_CHECKS.json", "PAYLOAD_SHA256SUMS.txt", "DELIVERY_README.md")]
    with zipfile.ZipFile(index_archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        index_members = {}
        for path in index_paths:
            archive.write(path, path.name)
            index_members[path.name] = dict(bytes=path.stat().st_size, sha256=sha(path))
        archive.writestr(MANIFEST, json.dumps(dict(stage="Stage3G", version=VERSION, members=index_members,
            manifest_self_hash_omitted=True, external_zip_sha_covers_manifest=True), indent=2) + "\n")
    index_check = verify_archive(index_archive, extract_root)
    write_json(output / "DELIVERY_INDEX_CHECK.json", dict(status="PASSED", **index_check))
    (output / "SHA256SUMS.txt").write_text(sums + f"{sha(index_archive)}  {index_archive.name}\n")
    print(json.dumps(dict(status="COMPLETED", output=str(output), package_count=len(archives) + 1,
        packages=[dict(name=path.name, bytes=path.stat().st_size, sha256=sha(path)) for path in archives + [index_archive]],
        actual_extraction_root=str(extract_root)), indent=2))


if __name__ == "__main__":
    main()
