#!/usr/bin/env python3
"""Host-only checks for the current XSAI emu path and AM test entrypoint."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class EmuRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xsai-emu-routing-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.noop = self.root / "XSAI with spaces"
        self.capture = self.root / "args.json"
        self.payload = self.root / "payload.bin"
        self.payload.write_bytes(b"\0")
        self.env = dict(os.environ, XS_PROJECT_ROOT=str(self.root),
                        NOOP_HOME=str(self.noop), CAPTURE=str(self.capture))
        self.env.pop("EMU_BIN", None)

    def stub(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json,os,sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
            "print('stub emu')\n"
        )
        path.chmod(0o755)

    def run_script(self, *flags):
        return subprocess.run(
            ["bash", str(REPO / "scripts/run-emu.sh"), *flags,
             "--log-dir", str(self.root / "logs"), str(self.payload)],
            env=self.env, text=True, capture_output=True, check=True,
        )

    def test_current_default_and_make_guard(self):
        emu = self.noop / "build/emu"
        self.stub(emu)
        result = self.run_script()
        self.assertIn(str(emu), result.stdout)
        self.assertEqual(json.loads(self.capture.read_text()),
                         ["-i", str(self.payload), "--no-diff"])
        # A cached current-path binary must not trigger a recursive build.
        subprocess.run(
            ["make", "-f", str(REPO / "Makefile"), "_ensure_emu",
             f"NOOP_HOME={self.noop}", "MAKE=/bin/false"],
            env=self.env, check=True, capture_output=True,
        )

    def test_explicit_binary_and_diff_logging(self):
        emu = self.root / "selected backend/emu"
        self.stub(emu)
        ref = self.root / "ref.so"
        ref.write_bytes(b"")
        self.env["EMU_BIN"] = str(emu)
        self.run_script("--log", "--diff", "--diff-so", str(ref), "-I", "100")
        self.assertEqual(json.loads(self.capture.read_text()),
                         ["-i", str(self.payload), f"--diff={ref}", "-I", "100"])
        subprocess.run(
            ["make", "-f", str(REPO / "Makefile"), "_ensure_emu",
             f"NOOP_HOME={self.noop}", "MAKE=/bin/false"],
            env=self.env, check=True, capture_output=True,
        )

    def test_matrix_route(self):
        # The recursive calls are replaced by a stub. Do not dry-run a real
        # orchestration target: make -n may still execute recursive recipes.
        spy = self.root / "make-spy"
        self.stub(spy)
        am = self.root / "nexus-am"
        subprocess.run(
            ["make", "-f", str(REPO / "Makefile"), "test-matrix",
             f"MAKE={spy}", f"AM_HOME={am}"],
            env=self.env, check=True, capture_output=True,
        )
        self.assertEqual(json.loads(self.capture.read_text()),
                         ["run-emu", f"PAYLOAD={am}/tests/ame-mmacc/build/ame-mmacc-riscv64-xs.bin"])
        text = (REPO / "Makefile").read_text()
        recipe = text.split("\ntest-matrix:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("ARCH=riscv64-xs TOOLCHAIN=LLVM", recipe)
        self.assertNotIn("ame0.6", recipe)


if __name__ == "__main__":
    unittest.main()
