"""Verify delivered ZIPs in a fresh directory using their own notebook importer.

This is an interface/cache verification. It neither creates scientific results
nor replaces any original run, package or checkpoint.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def snapshot(root: Path, directories: list[str], predictions_only: bool = False) -> dict:
    return {path.relative_to(root).as_posix(): digest(path)
            for directory in directories
            for path in sorted((root / directory).rglob("*"))
            if path.is_file() and (not predictions_only or path.name == "predictions.csv")}


def notebook_helpers(data: bytes) -> dict:
    notebook = json.loads(data)
    namespace = {"Path": Path}
    core_cells = 0
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        ast.parse(source, filename=f"delivered_notebook_cell_{index}")
        if "core" in cell.get("metadata", {}).get("tags", []):
            exec(compile(source, f"delivered_notebook_cell_{index}", "exec"), namespace)
            core_cells += 1
    require(core_cells > 0 and "import_zip" in namespace and "preflight" in namespace,
            "Delivered notebook lacks tested runtime/import helpers")
    return namespace


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", default="deliverables/stage2_20261010")
    parser.add_argument("--output", default="validation/stage2_delivery_replay_checks.json")
    parser.add_argument("--logs", default="validation/stage2_delivery_replay")
    args = parser.parse_args()
    packages = (ROOT / args.packages).resolve()
    output = (ROOT / args.output).resolve()
    logs = (ROOT / args.logs).resolve()
    require(packages.is_relative_to(ROOT) and output.is_relative_to(ROOT) and logs.is_relative_to(ROOT),
            "Package and validation paths must stay in the project")
    require(not output.exists() and not logs.exists(), "Preserve previous replay reports/logs; select a new output")
    python = ROOT / ".venv-stage2/bin/python"
    require(python.is_file(), "Verified stage-two Python is unavailable")
    require(Path(sys.executable).absolute() == python.absolute(),
            "Invoke this checker with the project's .venv-stage2/bin/python")
    logs.mkdir(parents=True)
    report = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "delivered-package interface/cache verification; excluded from scientific aggregate",
              "real_Colab_Drive_mount_verified": False, "GPU_execution_verified": False,
              "verification_script_sha256": digest(Path(__file__)), "checks": {}}
    try:
        receipt = json.loads((packages / "package_checks.json").read_text())
        require(receipt["status"] == "passed", "Package receipt did not pass")
        external = {}
        for line in (packages / "SHA256SUMS").read_text().splitlines():
            expected, name = line.split(maxsplit=1)
            require(Path(name).name == name and name.endswith(".zip"), "Unsafe external checksum path")
            require(len(expected) == 64 and name not in external, "Invalid duplicate/external checksum")
            external[name] = expected
        records = {item["filename"]: item for item in receipt["packages"]}
        require(set(external) == set(records), "External checksums and package receipt differ")
        for name, expected in external.items():
            require(digest(packages / name) == expected == records[name]["sha256"],
                    f"External ZIP SHA256 failed: {name}")
            require((packages / name).stat().st_size == records[name]["bytes"] < 24 * 1024 * 1024,
                    f"ZIP size check failed: {name}")
        report["checks"]["external_zip_sha256_and_sizes"] = records
        originals = snapshot(ROOT, ["runs/shared_v3_20261009/source", "runs/shared_v3_20261009/smoke"])
        code_names = [name for name in records if "Code_Data" in name]
        require(len(code_names) == 1, "One Code_Data ZIP is required")
        with zipfile.ZipFile(packages / code_names[0]) as packed:
            notebook_data = packed.read("notebooks/Wessex_Shared_Development_v3.ipynb")
        helpers = notebook_helpers(notebook_data)
        report["checks"]["importer_from_exact_delivered_notebook_sha256"] = hashlib.sha256(notebook_data).hexdigest()
        with tempfile.TemporaryDirectory(prefix="wessex_stage2_delivery_", dir="/tmp") as temporary:
            fresh = Path(temporary) / "project"
            imports = []
            for name in sorted(records, key=lambda item: ("Code_Data" not in item, item)):
                imports.append(helpers["import_zip"](packages / name, fresh, external[name]))
            require(not (fresh / "SHA256SUMS").exists() and not (fresh / "SHA256SUMS.txt").exists(),
                    "Per-package checksum manifests were incorrectly copied into shared ROOT")
            report["checks"]["all_ZIPs_merged_into_one_fresh_ROOT"] = imports
            report["checks"]["checksum_manifests_verified_without_copying"] = True
            preflight = helpers["preflight"](fresh, "configs/shared_v3_20261009/smoke.json")
            require(preflight["expected_jobs"] == 96, "Delivered smoke cohort changed")
            report["checks"]["delivered_preflight"] = preflight
            smoke_predictions = snapshot(fresh, ["runs/shared_v3_20261009/smoke"], predictions_only=True)
            source_files = snapshot(fresh, ["runs/shared_v3_20261009/source"])
            require(len(smoke_predictions) == 96, "Delivered smoke predictions are missing")
            require(smoke_predictions == {name: originals[name] for name in smoke_predictions},
                    "Delivered smoke predictions differ from original bytes")
            require(source_files == {name: originals[name] for name in source_files},
                    "Delivered source files differ from original bytes")
            command = [str(python), "-u", "-m", "wastewater.shared_experiment", "--config",
                       "configs/shared_v3_20261009/smoke.json"]
            env = helpers["project_env"](fresh)
            log = logs / "smoke_cached_command.log"
            with log.open("w") as stream:
                result = subprocess.run(command, cwd=fresh, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, check=False)
            require(result.returncode == 0, f"Delivered smoke failed; see {log.relative_to(ROOT)}")
            manifest = json.loads((fresh / "runs/shared_v3_20261009/smoke/manifest.json").read_text())
            require(manifest["status"] == "completed" and manifest["completed_jobs"] == 96,
                    "Delivered smoke did not finish all tasks")
            require(manifest["counts_this_call"] == {"completed": 0, "cached": 96, "failed": 0},
                    "Smoke replay fitted a target model instead of reading all 96 caches")
            require(snapshot(fresh, ["runs/shared_v3_20261009/smoke"], predictions_only=True) == smoke_predictions,
                    "A delivered smoke prediction changed during cache replay")
            require(snapshot(fresh, ["runs/shared_v3_20261009/source"]) == source_files,
                    "A delivered source checkpoint/search file changed during cache replay")
            report["checks"]["smoke_replay"] = {"command": command, "counts_this_call": manifest["counts_this_call"],
                "prediction_files_byte_unchanged": len(smoke_predictions),
                "source_files_byte_unchanged": len(source_files),
                "target_models_retrained": False,
                "source_ridge": "lightweight source Ridge reconstruction occurs; cached GRU checkpoints are unchanged",
                "command_log": log.relative_to(ROOT).as_posix()}
            independent = [str(python), "scripts/validate_stage2.py", "--run",
                           "runs/shared_v3_20261009/smoke", "--seeds", "20261009", "--output",
                           "validation/delivery_smoke_checks.json"]
            with (logs / "independent_validation_command.log").open("w") as stream:
                result = subprocess.run(independent, cwd=fresh, env=env, stdout=stream,
                                        stderr=subprocess.STDOUT, check=False)
            require(result.returncode == 0, "Independent delivered smoke validation failed")
            checks = json.loads((fresh / "validation/delivery_smoke_checks.json").read_text())
            require(checks["status"] == "passed" and checks["rows"] == 23040 and checks["stations"] == 2,
                    "Independent smoke validation has an unexpected cohort")
            report["checks"]["independent_saved_predictions_validation"] = checks
            (logs / "independent_smoke_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        require(snapshot(ROOT, ["runs/shared_v3_20261009/source", "runs/shared_v3_20261009/smoke"]) == originals,
                "An original source/smoke artifact changed")
        for name, expected in external.items():
            require(digest(packages / name) == expected, f"Original delivery ZIP changed: {name}")
        report["checks"]["original_source_smoke_and_delivery_ZIPs_unchanged"] = True
        report["checks"]["original_source_and_smoke_files_preserved"] = len(originals)
        report["checks"]["fresh_temporary_project_removed"] = True
        report["status"] = "passed"
    except BaseException:
        report["status"] = "failed"
        report["error"] = traceback.format_exc()
        raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
