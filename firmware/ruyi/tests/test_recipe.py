#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "build.sh"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecipeInputTests(unittest.TestCase):
    def make_manifest(self, directory, checksum="0" * 64):
        source = directory / "input"
        source.write_bytes(b"fixed")
        artifact = {"path": "input", "url": None, "sha256": checksum}
        return {
            "schema_version": 1,
            "header_abi": {
                "python": "3.13.8", "torch": "2.13.0",
                "libc": "test", "cxx11_abi": "0",
            },
            "artifacts": {
                "oci_rootfs": artifact, "kernel": artifact, "dtb": artifact,
                "initramfs": artifact, "headers": artifact,
            },
            "rpms": [{
                "name": "test", "version": "1", "arch": "riscv64",
                **artifact,
            }],
        }

    def run_validate(self, directory, manifest):
        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest))
        return subprocess.run(
            ["bash", str(ENTRY), "validate", "--manifest", str(path)],
            text=True, capture_output=True)

    def test_missing_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest = self.make_manifest(directory)
            manifest["artifacts"]["kernel"]["sha256"] = None
            result = self.run_validate(directory, manifest)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sha256", result.stderr)

    def test_bad_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            result = self.run_validate(directory, self.make_manifest(directory))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sha256 mismatch", result.stderr)

    def test_fixed_local_inputs_validate(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "input"
            source.write_bytes(b"fixed")
            result = self.run_validate(directory, self.make_manifest(directory, sha(source)))
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
