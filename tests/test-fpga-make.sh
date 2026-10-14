#!/usr/bin/env bash
# Check top-level FPGA routing without running recursive orchestration targets.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
db="$(mktemp)"
trap 'rm -f "$db"' EXIT
make -qp > "$db" 2>/dev/null || true
for target in fpga-program fpga-sync-bitstream fpga-reset run-fpga fpga-run-bitstream test-fpga; do
    grep -q "^${target}:" "$db"
done
program="$(make -n fpga-program)"
reset="$(make -n fpga-reset)"
sync="$(make -n fpga-sync-bitstream)"
[[ "$program" == *"./scripts/fpga-program-bitstream.sh"* ]]
[[ "$reset" == *"./scripts/fpga-run-ai.sh --reset-only"* ]]
[[ "$sync" == *"./scripts/fpga-program-bitstream.sh --sync-only"* ]]

# Check ordered recipes statically: make -n on recursive targets is not inert.
python3 - "$repo_root/Makefile" <<'PY'
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text()
recipe = text.split("\nfpga-run-bitstream: _ensure_fpga_payload\n", 1)[1].split("\n\n", 1)[0]
assert "scripts/fpga-program-run.sh" in recipe
assert "$(RUN_NEMU_PAYLOAD)" in recipe
assert "FPGA_KILL_UART_READERS ?= 0" in text
assert "FPGA_PASS_PATTERN ?=\n" in text
assert "FPGA_RTL" not in recipe
assert "FPGA_LTX ?= $(FPGA_REMOTE_BIT_HOME)/pcie_part_gating_wrapper.ltx" in text
PY
echo "[test-fpga-make] offline routing passed"
