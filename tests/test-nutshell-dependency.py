#!/usr/bin/env python3
"""Offline tests for make test's on-demand NutShell dependency."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[1]


class NutShellDependency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xsai-test-nutshell-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout with spaces"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy2(REPO / "scripts/ensure-test-deps.sh",
                     self.root / "scripts/ensure-test-deps.sh")
        (self.root / "scripts/ensure-test-deps.sh").chmod(0o755)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.jsonl"
        self.write_git_stub()

    def write_git_stub(self):
        (self.bin / "git").write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            with open(os.environ["CALLS"], "a") as stream:
                stream.write(json.dumps(args) + "\\n")
            if os.environ.get("FAIL_GIT") == "1":
                print("fatal: access denied", file=sys.stderr)
                sys.exit(128)
            if "--checkout" not in args or "NutShell" not in args:
                print("fatal: expected explicit NutShell checkout", file=sys.stderr)
                sys.exit(2)
            path = Path(os.environ["ROOT"]) / "NutShell"
            path.mkdir(parents=True, exist_ok=True)
            (path / "Makefile").write_text("# test stub\\n")
        """))
        (self.bin / "git").chmod(0o755)

    def run_helper(self, **extra):
        env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            CALLS=str(self.calls),
            ROOT=str(self.root),
            **extra,
        )
        return subprocess.run(
            ["bash", str(self.root / "scripts/ensure-test-deps.sh")],
            env=env, text=True, capture_output=True, timeout=15,
        )

    def calls_list(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_missing_submodule_is_initialized_with_checkout_override(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "NutShell/Makefile").exists())
        self.assertEqual(len(self.calls_list()), 1)
        call = self.calls_list()[0]
        self.assertEqual(call[:2], ["-c", "submodule.NutShell.update=checkout"])
        self.assertEqual(call[-4:], ["update", "--init", "--checkout", "NutShell"])
        self.assertIn("initializing it now", result.stdout)

    def test_initialized_submodule_is_not_touched(self):
        nutshell = self.root / "NutShell"
        nutshell.mkdir()
        (nutshell / "Makefile").write_text("# existing\\n")
        result = self.run_helper(FAIL_GIT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls_list(), [])
        self.assertEqual((nutshell / "Makefile").read_text(), "# existing\\n")

    def test_failure_is_actionable_and_non_silent(self):
        result = self.run_helper(FAIL_GIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Failed to initialize required NutShell", result.stderr)
        self.assertIn("git submodule update --init --checkout NutShell",
                      result.stderr)

    def test_make_test_declares_the_prerequisite(self):
        text = (REPO / "Makefile").read_text()
        self.assertIn("test: _ensure_test_dependencies", text)
        self.assertIn("./scripts/ensure-test-deps.sh", text)
        self.assertIn("test-smoke", (REPO / "scripts/smoke-test.sh").read_text())


if __name__ == "__main__":
    unittest.main()
