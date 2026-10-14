#!/usr/bin/env bash
# Stage and program an explicit bit/LTX pair without deleting prior bundles.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XS_PROJECT_ROOT="${XS_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/fpga/common.sh"
HOST="${FPGA_HOST:-fpga}"
REMOTE_SETUP="${FPGA_REMOTE_SETUP-source /tools/Xilinx/Vivado_Lab/2020.2/settings64.sh}"
BIT_HOME="${FPGA_BIT_HOME-}"
REMOTE_HOME="${FPGA_REMOTE_BIT_HOME:-/home/fpga/xsai-bitstream/current}"
PCIE_SUDO="${FPGA_PCIE_SUDO-sudo -n}"
PCIE_RESET="${FPGA_PROGRAM_PCIE_RESET:-1}"
ASSERT_RESET="${FPGA_PROGRAM_ASSERT_RESET:-1}"
SYNC_ONLY=0
PROGRAM_ONLY=0
usage() {
    echo "Usage: FPGA_BIT_HOME=<explicit directory> scripts/fpga-program-bitstream.sh [--sync-only]"
    echo "Exactly one nonempty .bit/.ltx pair is required; no latest-directory guessing."
    echo "Previous remote bundles are retained. PCIe removal requires explicit FPGA_PCIE_BDF."
}
while (( $# )); do
    case "$1" in
        --sync-only) SYNC_ONLY=1; shift ;;
        --program-only) PROGRAM_ONLY=1; shift ;;
        --no-pcie-reset) PCIE_RESET=0; shift ;;
        --no-reset) ASSERT_RESET=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
[[ "$PROGRAM_ONLY" == 0 ]] || {
    echo "error: unverified --program-only is unsupported; use an explicit local hashed bundle" >&2
    exit 2
}
fpga_bool FPGA_PROGRAM_PCIE_RESET "$PCIE_RESET"
fpga_bool FPGA_PROGRAM_ASSERT_RESET "$ASSERT_RESET"
fpga_positive FPGA_XDMA_WAIT_SECS "${FPGA_XDMA_WAIT_SECS:-10}"
fpga_bool FPGA_XDMA_RELOAD_ON_MISSING "${FPGA_XDMA_RELOAD_ON_MISSING:-0}"
fpga_path FPGA_REMOTE_BIT_HOME "$REMOTE_HOME"
[[ -n "$BIT_HOME" && -d "$BIT_HOME" ]] || { usage >&2; exit 2; }
shopt -s nullglob
bits=("$BIT_HOME"/*.bit)
probes=("$BIT_HOME"/*.ltx)
[[ "${#bits[@]}" == 1 && "${#probes[@]}" == 1 && -s "${bits[0]}" && -s "${probes[0]}" ]] || {
    echo "error: exactly one nonempty bit/LTX pair required" >&2; exit 2
}
[[ "$(basename "${bits[0]}" .bit)" == "$(basename "${probes[0]}" .ltx)" ]] || {
    echo "error: bit/LTX stems differ; make the intended pair explicit in a dedicated directory" >&2
    exit 2
}
if [[ "$SYNC_ONLY" == 0 && "$PCIE_RESET" == 1 ]]; then
    [[ "${FPGA_PCIE_BDF:-}" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]$ ]] || {
        echo "error: explicit FPGA_PCIE_BDF required for PCIe remove/rescan" >&2; exit 2
    }
fi
for helper in program_bitstream.tcl reset_cpu.tcl pcie-remove.sh pcie-rescan.sh; do
    [[ -s "$SCRIPT_DIR/fpga/$helper" ]]
done
for tool in ssh scp sha256sum; do command -v "$tool" >/dev/null; done
bit_digest="$(sha256sum "${bits[0]}" | awk '{print $1}')"
ltx_digest="$(sha256sum "${probes[0]}" | awk '{print $1}')"
run_id="$(date +%Y%m%d-%H%M%S)-$$"
# Immutable unique bundle: failed/repeated uploads do not replace current inputs.
remote_bundle="${REMOTE_HOME%/}/bundles/${bit_digest:0:16}-${run_id}"
remote_bit="$remote_bundle/$(basename "${bits[0]}")"
remote_ltx="$remote_bundle/$(basename "${probes[0]}")"
program_tcl="/tmp/xsai-program-${run_id}.tcl"
reset_tcl="/tmp/xsai-program-reset-${run_id}.tcl"
uploaded=0
cleanup() {
    local rc=$?
    trap - EXIT
    if [[ "$uploaded" == 1 ]]; then
        fpga_remote "rm -f -- $(fpga_quote "$program_tcl") $(fpga_quote "$reset_tcl")" >/dev/null 2>&1 || true
    fi
    fpga_release
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
fpga_acquire
fpga_remote "mkdir -p -- $(fpga_quote "${REMOTE_HOME%/}/bundles"); mkdir -- $(fpga_quote "$remote_bundle")"
scp -- "${bits[0]}" "$HOST:$remote_bit"
scp -- "${probes[0]}" "$HOST:$remote_ltx"
fpga_remote "set -e; test $(fpga_quote "$bit_digest") = \"\$(sha256sum -- $(fpga_quote "$remote_bit") | cut -d ' ' -f1)\"; test $(fpga_quote "$ltx_digest") = \"\$(sha256sum -- $(fpga_quote "$remote_ltx") | cut -d ' ' -f1)\""
mkdir -p "$XS_PROJECT_ROOT/log"
manifest="$XS_PROJECT_ROOT/log/fpga-program-${run_id}.txt"
{
    echo "host=$HOST"
    echo "remote_bundle=$remote_bundle"
    echo "remote_bit=$remote_bit"
    echo "remote_ltx=$remote_ltx"
    echo "bit_sha256=$bit_digest"
    echo "ltx_sha256=$ltx_digest"
    echo "mode=$([[ "$SYNC_ONLY" == 1 ]] && echo sync-only || echo program)"
} > "$manifest"
if [[ "$SYNC_ONLY" == 1 ]]; then
    echo "[fpga] verified upload only; board not programmed"
    echo "[fpga] manifest: $manifest"
    exit 0
fi
scp -- "$SCRIPT_DIR/fpga/program_bitstream.tcl" "$HOST:$program_tcl"
scp -- "$SCRIPT_DIR/fpga/reset_cpu.tcl" "$HOST:$reset_tcl"
uploaded=1
pcie_script() {
    local args
    printf -v args '%q ' \
        "FPGA_PCIE_BDF=${FPGA_PCIE_BDF-}" "FPGA_PCIE_SUDO=$PCIE_SUDO" \
        "FPGA_XDMA_REQUIRED_DEVICES=${FPGA_XDMA_REQUIRED_DEVICES:-/dev/xdma0_c2h_0 /dev/xdma0_h2c_0 /dev/xdma0_user /dev/xdma0_bypass}" \
        "FPGA_XDMA_RELOAD_ON_MISSING=${FPGA_XDMA_RELOAD_ON_MISSING:-0}" \
        "FPGA_XDMA_MODULE=${FPGA_XDMA_MODULE:-xdma}" \
        "FPGA_XDMA_WAIT_SECS=${FPGA_XDMA_WAIT_SECS:-10}"
    ssh -o BatchMode=yes "$HOST" "env $args bash -s" < "$SCRIPT_DIR/fpga/$1"
}
if [[ "$PCIE_RESET" == 1 ]]; then
    if [[ -n "${FPGA_PCIE_REMOVE_CMD:-}" ]]; then fpga_remote "$FPGA_PCIE_REMOVE_CMD"
    else pcie_script pcie-remove.sh; fi
fi
fpga_remote_setup "vivado -mode batch -source $(fpga_quote "$program_tcl") -tclargs $(fpga_quote "$remote_bundle")"
if [[ "$PCIE_RESET" == 1 ]]; then
    if [[ -n "${FPGA_PCIE_RESCAN_CMD:-}" ]]; then fpga_remote "$FPGA_PCIE_RESCAN_CMD"
    else pcie_script pcie-rescan.sh; fi
fi
if [[ "$ASSERT_RESET" == 1 ]]; then
    fpga_remote_setup "vivado -mode batch -source $(fpga_quote "$reset_tcl") -tclargs $(fpga_quote "$remote_ltx") 1"
fi
echo "programmed=1" >> "$manifest"
if [[ -n "${FPGA_PROGRAM_RESULT_FILE:-}" ]]; then
    printf '%s\n' "$remote_ltx" > "$FPGA_PROGRAM_RESULT_FILE"
fi
echo "[fpga] programmed verified bundle; manifest: $manifest"
echo "[fpga] run with FPGA_LTX=$remote_ltx"
