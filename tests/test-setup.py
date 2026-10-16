#!/usr/bin/env python3
"""Offline regression checks for public-checkout initialization."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[1]
REAL_MAKE = shutil.which("make")
OPTIONAL = ("llvm-project-ame", "riscv-matrix-spec")


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xsai-setup-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout with spaces"
        for relative in ("scripts/setup.sh", "scripts/build-llvm.sh", "Makefile",
                         "mk/pldm.mk", "mk/memory.mk"):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relative, target)
        (self.root / "env.sh").write_text(
            'export XS_PROJECT_ROOT="$ROOT"\n'
            'export NEMU_HOME="$ROOT/NEMU"\n'
            'export AM_HOME="$ROOT/nexus-am"\n'
            'export NOOP_HOME="$ROOT/XSAI"\n'
        )
        self.calls = self.root / "calls.jsonl"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.write_tool("git", """
            import json, os, sys
            args = sys.argv[1:]
            with open(os.environ["CALLS"], "a") as f:
                f.write(json.dumps({"tool": "git", "args": args,
                                    "prompt": os.environ.get("GIT_TERMINAL_PROMPT"),
                                    "askpass": os.environ.get("GIT_ASKPASS")}) + "\\n")
            optional = args[-1] in ("llvm-project-ame", "riscv-matrix-spec")
            if ((optional and os.environ.get("FAIL_OPTIONAL") == "1") or
                    os.environ.get("FAIL_REQUIRED", "") in args):
                for _ in range(10):
                    print("fatal: repository unavailable", file=sys.stderr)
                sys.exit(128)
        """)
        self.write_tool("make", """
            import json, os, sys
            args = sys.argv[1:]
            with open(os.environ["CALLS"], "a") as f:
                f.write(json.dumps({"tool": "make", "args": args}) + "\\n")
            if os.environ.get("FAIL_NESTED", "") in args:
                print("nested initialization failed", file=sys.stderr)
                sys.exit(2)
        """)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        CALLS=str(self.calls), GIT_FORCE_INIT="0",
                        INIT_OPTIONAL_SUBMODULES="0")
        for variable in ("MAKEFLAGS", "MFLAGS", "FAIL_OPTIONAL", "FAIL_REQUIRED",
                         "FAIL_NESTED"):
            self.env.pop(variable, None)

    def write_tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body))
        path.chmod(0o755)

    def run_setup(self, mode="dev", **variables):
        return subprocess.run(
            ["bash", str(self.root / "scripts/setup.sh"), mode],
            env=dict(self.env, **variables), text=True, capture_output=True,
            timeout=15,
        )

    def commands(self, tool):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()
                if json.loads(line)["tool"] == tool]

    def test_default_skips_optional_sources_without_attempting_clones(self):
        result = self.run_setup(FAIL_OPTIONAL="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands("git")
        self.assertEqual(len(commands), 2)
        for call in commands:
            self.assertNotIn("--force", call["args"])
            for optional in OPTIONAL:
                self.assertNotIn(optional, call["args"])
        for required in ("NEMU", "qemu", "nexus-am", "XSAI"):
            self.assertTrue(any(required in call["args"] for call in commands))
        self.assertEqual([call["args"] for call in self.commands("make")],
                         [["-C", "XSAI", "init-force"],
                          ["-C", "firmware", "init-force"]])
        self.assertIn("Skipping optional sources", result.stdout)
        self.assertIn("Getting AME LLVM", result.stdout)
        self.assertFalse((self.root / "log/setup").exists())

    def test_source_opt_in_overrides_update_none(self):
        result = self.run_setup(INIT_OPTIONAL_SUBMODULES="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands("git")
        for optional in OPTIONAL:
            call = next(call for call in commands if optional in call["args"])
            self.assertIn("--checkout", call["args"])
            self.assertNotIn("--force", call["args"])
            self.assertEqual(call["prompt"], "0")
            self.assertEqual(call["askpass"], "/bin/false")
        compiler = next(call for call in commands
                        if "llvm-project-ame" in call["args"])
        self.assertIn("--depth", compiler["args"])
        self.assertIn("Optional source ready", result.stdout)

    def test_unavailable_optional_sources_are_quiet_and_keep_full_logs(self):
        result = self.run_setup(INIT_OPTIONAL_SUBMODULES="1", FAIL_OPTIONAL="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("fatal:", result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("Skipped optional source:"), 2)
        for optional in OPTIONAL:
            log = self.root / "log/setup" / f"{optional}.log"
            self.assertIn(str(log), result.stdout)
            self.assertEqual(log.read_text().count("fatal:"), 10)
        self.assertEqual(len(self.commands("make")), 2)

    def test_make_init_force_passes_optional_flag_and_force(self):
        result = subprocess.run(
            [REAL_MAKE, "init-force", "INIT_OPTIONAL_SUBMODULES=1"],
            cwd=self.root, env=self.env, text=True, capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        commands = self.commands("git")
        self.assertEqual(len(commands), 4)
        self.assertTrue(all("--force" in call["args"] for call in commands))

    def test_required_source_failure_is_not_hidden(self):
        result = self.run_setup(FAIL_REQUIRED="NEMU",
                                INIT_OPTIONAL_SUBMODULES="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fatal:", result.stderr)
        self.assertEqual(len(self.commands("git")), 1)
        self.assertEqual(self.commands("make"), [])
        self.assertNotIn("Skipped optional", result.stdout)

    def test_nested_initialization_failure_is_not_hidden(self):
        result = self.run_setup(FAIL_NESTED="XSAI",
                                INIT_OPTIONAL_SUBMODULES="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nested initialization failed", result.stderr)
        self.assertEqual(len(self.commands("git")), 2)
        self.assertEqual(len(self.commands("make")), 1)

    def test_user_mode_keeps_its_required_only_route(self):
        result = self.run_setup("user", INIT_OPTIONAL_SUBMODULES="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call["args"] for call in self.commands("git")],
                         [["submodule", "update", "--init", "qemu"]])
        self.assertEqual([call["args"] for call in self.commands("make")],
                         [["-C", "firmware", "init", "GIT_FORCE_INIT=0"]])

    def test_invalid_flag_fails_before_network_or_nested_setup(self):
        result = self.run_setup(INIT_OPTIONAL_SUBMODULES="typo")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be 0 or 1", result.stderr)
        self.assertEqual(self.commands("git"), [])
        self.assertEqual(self.commands("make"), [])

    def test_invalid_mode_fails_before_network(self):
        result = self.run_setup("typo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stderr)
        self.assertEqual(self.commands("git"), [])

    def test_source_build_without_sources_explains_prebuilt_alternative(self):
        result = subprocess.run(
            ["bash", str(self.root / "scripts/build-llvm.sh")],
            env=self.env, text=True, capture_output=True, timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Getting AME LLVM", result.stderr)
        self.assertIn("INIT_OPTIONAL_SUBMODULES=1", result.stderr)
        self.assertNotIn("cross compiler not found", result.stderr)
        self.assertFalse((self.root / "local").exists())
        self.assertEqual(self.commands("git"), [])


if __name__ == "__main__":
    unittest.main()
