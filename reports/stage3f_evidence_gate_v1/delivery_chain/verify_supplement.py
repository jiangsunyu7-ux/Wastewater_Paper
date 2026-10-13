"""Verify the actual small supplement without unpacking or running science."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_file", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    container_sha = hashlib.sha256(args.zip_file.read_bytes()).hexdigest()
    if args.expected_sha256:
        assert container_sha == args.expected_sha256, "Container SHA256 mismatch"
    with zipfile.ZipFile(args.zip_file) as archive:
        assert archive.testzip() is None, "CRC failed"
        manifest = json.loads(archive.read("SUPPLEMENT_MANIFEST.json"))
        expected = manifest["members_sha256"]
        assert set(archive.namelist()) == set(expected) | {"SHA256SUMS", "SUPPLEMENT_MANIFEST.json"}
        for name, value in expected.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == value, name
        checksum_rows = [line.split("  ", 1) for line in archive.read("SHA256SUMS").decode().splitlines()]
        assert {name: value for value,name in checksum_rows} == expected
    print(json.dumps({"status": "PASSED", "sha256": container_sha,
        "members": len(archive.namelist()), "work": "CRC/member SHA only; no science executed"}))

if __name__ == "__main__":
    main()
