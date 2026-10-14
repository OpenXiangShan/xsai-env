#!/usr/bin/env bash
# Host-only tests: no FPGA/Vivado, device access or remote SSH.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
for script in scripts/fpga-*.sh scripts/fpga/*.sh; do
    [[ -f "$script" ]] || continue
    bash -n "$script"
done
found=0
for test in tests/test-fpga-*.sh; do
    [[ -f "$test" ]] || continue
    found=1
    bash "$test"
done
for test in tests/test-fpga-*.py; do
    [[ -f "$test" ]] || continue
    found=1
    python3 "$test"
done
for test in tests/test-fpga-*.tcl; do
    [[ -f "$test" ]] || continue
    found=1
    tclsh "$test"
done
if [[ "$found" == 0 ]]; then
    echo "error: no FPGA regression tests found" >&2
    exit 1
fi
echo "[test-fpga] offline gates passed"
