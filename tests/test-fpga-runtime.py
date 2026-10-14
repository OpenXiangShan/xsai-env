#!/usr/bin/env python3
"""Offline subprocess tests. SSH/SCP/Vivado/tmux/setpci are never real here."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MOCK = r'''#!/usr/bin/env python3
import os, pathlib, shlex, shutil, subprocess, sys
tool = pathlib.Path(sys.argv[0]).name
scratch = pathlib.Path(os.environ["MOCK_ROOT"])
with (scratch/"commands").open("a") as out:
    out.write(tool+" "+repr(sys.argv[1:])+"\n")
def mapped(s):
    protected = s.replace(str(scratch), "__MOCK_SCRATCH__")
    return protected.replace("/tmp/xsai-", str(scratch/"remote"/"xsai-")).replace("__MOCK_SCRATCH__", str(scratch))
if tool == "ssh":
    command = mapped(sys.argv[-1])
    args = shlex.split(command)
    inner = args[2] if args[:2] == ["bash", "-lc"] else command
    if "exec flock -n" in inner:
        if os.environ.get("MOCK_BUSY") == "lease": sys.exit(1)
        print("XSAI_LOCK_READY", flush=True)
        sys.stdin.buffer.read()
        sys.exit(0)
    if "pgrep -fa" in inner:
        sys.exit({"reader":0, "ssh":255}.get(os.environ.get("MOCK_BUSY"), 1))
    if args[:2] == ["bash", "-s"]:
        content = sys.stdin.buffer.read()
        sys.exit(subprocess.run(args, input=content).returncode)
    if args[:2] == ["bash", "-lc"]:
        # Avoid login-shell environment or user startup scripts in mock execution.
        sys.exit(subprocess.run(["bash","-c",args[2]]).returncode)
    sys.exit(subprocess.run(["bash","-c",command], input=sys.stdin.buffer.read()).returncode)
if tool == "scp":
    src, dst = sys.argv[-2:]
    if src.startswith("mock:"): src = mapped(src[5:])
    if dst.startswith("mock:"): dst = mapped(dst[5:])
    shutil.copyfile(src,dst)
    if os.environ.get("MOCK_CORRUPT") == "1" and ".upload-" in dst:
        pathlib.Path(dst).write_bytes(b"corrupted")
    sys.exit(0)
if tool == "vivado":
    sys.exit(int(os.environ.get("MOCK_VIVADO_RC","0")))
if tool == "tmux":
    if sys.argv[1] == "has-session":
        sys.exit(0 if os.environ.get("MOCK_TMUX_BUSY") == "1" else 1)
    sys.exit(0)
if tool == "setpci":
    state=scratch/"pci-command"
    if any("COMMAND=" in arg for arg in sys.argv):
        state.write_text("0006")
    else: print(state.read_text())
    sys.exit(0)
if tool in ("udevadm", "modprobe"):
    sys.exit(0)
raise SystemExit("unexpected mocked command "+tool)
'''


class Runtime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="xsai-fpga-test.")
        self.root = pathlib.Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "remote").mkdir()
        for tool in ("ssh", "scp", "vivado", "tmux", "setpci", "udevadm", "modprobe"):
            path = self.bin / tool
            path.write_text(MOCK)
            path.chmod(0o755)
        self.payload = self.root / "payload with spaces.bin"
        self.payload.write_bytes(b"fixed workload")
        self.ltx = self.root / "probes with spaces.ltx"
        self.ltx.write_text("fixed probes")
        self.driver = self.root / "driver"
        self.driver.write_bytes(b"bare-metal driver image")
        self.loader = self.root / "loader"
        self.loader.write_text("#!/bin/bash\nexit 0\n")
        self.loader.chmod(0o755)
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith("FPGA_"):
                self.env.pop(key)
        self.env.update(
            MOCK_ROOT=str(self.root),
            PATH=str(self.bin) + ":" + os.environ["PATH"],
            XS_PROJECT_ROOT=str(self.root),
            FPGA_HOST="mock",
            FPGA_REMOTE_SETUP="export PATH=" + str(self.bin) + ":$PATH",
            FPGA_LTX=str(self.ltx),
            FPGA_DRIVER=str(self.driver),
            FPGA_XDMA_PROCESS=str(self.loader),
            FPGA_REMOTE_PAYLOAD=str(self.root / "remote" / "cached payload.bin"),
            FPGA_TIMEOUT="5",
            FPGA_UART_CMD="printf 'WORKLOAD_PASS\\n'",
            FPGA_PASS_PATTERN="WORKLOAD_PASS",
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name, *args, **changes):
        env = self.env | changes
        return subprocess.run(
            ["bash", str(ROOT / "scripts" / name), *args],
            env=env, capture_output=True, text=True, timeout=15)

    def calls(self):
        path = self.root / "commands"
        return path.read_text() if path.exists() else ""

    def test_pass_and_cache(self):
        one = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload))
        self.assertEqual(one.returncode, 0, one.stdout + one.stderr)
        before = self.calls().count(".upload-")
        two = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload))
        self.assertEqual(two.returncode, 0, two.stdout + two.stderr)
        self.assertIn("SHA256 matches", two.stdout)
        self.assertEqual(before, self.calls().count(".upload-"))
        self.assertNotIn("pkill", self.calls())

    def test_failure_precedence_and_eof(self):
        failed = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload),
                                 FPGA_UART_CMD="printf 'WORKLOAD_PASS FAIL\\n'",
                                 FPGA_FAIL_PATTERN="FAIL")
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        eof = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload),
                             FPGA_UART_CMD="printf 'incomplete\\n'")
        self.assertEqual(eof.returncode, 3, eof.stdout + eof.stderr)

    def test_timeout_and_reset_error(self):
        timed = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload),
                               FPGA_UART_CMD="sleep 10", FPGA_TIMEOUT="1")
        self.assertEqual(timed.returncode, 124, timed.stdout + timed.stderr)
        failed = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload),
                                MOCK_VIVADO_RC="9")
        self.assertEqual(failed.returncode, 9)

    def test_bad_inputs_no_remote_calls(self):
        for change in ({"FPGA_TIMEOUT": "0"}, {"FPGA_UART_MODE": "bad"},
                       {"FPGA_FAIL_PATTERN": "["}, {"FPGA_KILL_UART_READERS": "1"}):
            result = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload), **change)
            self.assertEqual(result.returncode, 2)
        self.assertEqual(self.calls(), "")
        self.assertEqual(self.run_script("fpga-run-ai.sh", "--payload").returncode, 2)

    def test_busy_and_unreadable_ownership(self):
        for busy in ("lease", "reader", "ssh"):
            result = self.run_script("fpga-run-ai.sh", "--reset-only", MOCK_BUSY=busy)
            self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("scp ", self.calls())
        self.assertNotIn("vivado -mode", self.calls())

    def test_interactive_preserves_existing_session(self):
        result = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload),
                                 FPGA_UART_MODE="interactive", MOCK_TMUX_BUSY="1")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("ssh ", self.calls())
        launched = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload),
                                   FPGA_UART_MODE="interactive")
        self.assertEqual(launched.returncode, 0)
        self.assertIn("--interactive-worker", self.calls())
        self.assertNotIn("scp ", self.calls())

    def test_upload_corruption_blocks_reset(self):
        result = self.run_script("fpga-run-ai.sh", "--payload", str(self.payload),
                                 MOCK_CORRUPT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("vivado -mode", self.calls())

    def bundle(self):
        path = self.root / "bit bundle"
        path.mkdir()
        (path / "design.bit").write_bytes(b"bitstream")
        (path / "design.ltx").write_text("probes")
        return path

    def test_program_explicit_bundle_and_result(self):
        result_file = self.root / "result"
        result = self.run_script("fpga-program-bitstream.sh",
                                 FPGA_BIT_HOME=str(self.bundle()),
                                 FPGA_REMOTE_BIT_HOME=str(self.root / "remote" / "bits"),
                                 FPGA_PROGRAM_PCIE_RESET="0",
                                 FPGA_PROGRAM_ASSERT_RESET="0",
                                 FPGA_PROGRAM_RESULT_FILE=str(result_file))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result_file.read_text().rstrip().endswith("/design.ltx"))
        self.assertNotIn("*.bit", self.calls())
        self.assertIn("/bundles/", self.calls())

    def test_program_ambiguity_preflight(self):
        bundle = self.bundle()
        (bundle / "second.bit").write_bytes(b"other")
        result = self.run_script("fpga-program-bitstream.sh", "--sync-only",
                                 FPGA_BIT_HOME=str(bundle))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.calls(), "")
        result = self.run_script("fpga-program-bitstream.sh", "--program-only")
        self.assertEqual(result.returncode, 2)

    def test_pcie_selected_function_and_command_bits(self):
        sysfs = self.root / "sysfs"
        bdf = "0000:03:00.0"
        device = sysfs / "devices" / bdf
        device.mkdir(parents=True)
        for name, value in (("vendor", "0x10ee\n"), ("remove", ""), ("config", "")):
            (device / name).write_text(value)
        (sysfs / "rescan").write_text("")
        (self.root / "pci-command").write_text("0000")
        required = self.root / "xdma_user"
        required.touch()
        env = dict(FPGA_PCIE_SYSFS_ROOT=str(sysfs), FPGA_PCIE_BDF=bdf,
                   FPGA_PCIE_SUDO="", FPGA_XDMA_REQUIRED_DEVICES=str(required))
        result = self.run_script("fpga/pcie-rescan.sh", **env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / "pci-command").read_text(), "0006")
        result = self.run_script("fpga/pcie-remove.sh", **env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((device / "remove").read_text(), "1\n")
        bad = self.run_script("fpga/pcie-remove.sh", **(env | {"FPGA_PCIE_BDF": ""}))
        self.assertEqual(bad.returncode, 2)


if __name__ == "__main__":
    unittest.main()
