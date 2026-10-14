import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def runtime_manifest(root):
    root = Path(root).resolve()
    def git(*args):
        p = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
        return p.stdout.strip() if p.returncode == 0 else None
    files = {}
    for folder in ["src", "tests", "scripts", "configs"]:
        for p in sorted((root / folder).rglob("*")):
            if p.is_file() and p.suffix in {".py", ".sh", ".json"}:
                files[str(p.relative_to(root))] = sha256(p)
    dependencies = {}
    for name in ["numpy", "pandas", "scipy", "scikit-learn", "matplotlib"]:
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "not_installed"
    return {"git_head": git("rev-parse", "HEAD"), "git_status": git("status", "--short"),
            "code_sha256": files, "python": platform.python_version(),
            "platform": platform.platform(), "dependencies": dependencies}
