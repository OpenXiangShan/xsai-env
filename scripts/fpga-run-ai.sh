#!/usr/bin/env bash
# Load/reset/observe one FPGA workload. This is not a bitstream builder.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XS_PROJECT_ROOT="${XS_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
source "$SCRIPT_DIR/fpga/common.sh"
HOST="${FPGA_HOST:-fpga}"
REMOTE_SETUP="${FPGA_REMOTE_SETUP-source /tools/Xilinx/Vivado_Lab/2020.2/settings64.sh}"
LTX="${FPGA_LTX:-/home/fpga/xsai-bitstream/current/pcie_part_gating_wrapper.ltx}"
DRIVER="${FPGA_DRIVER:-~/nexus-am/apps/dse-driver-ai/build/dse-driver-ai-riscv64-xs-driver.bin}"
LOADER="${FPGA_XDMA_PROCESS:-~/ai/xdma_process/build/xdma_process}"
REMOTE_SUDO="${FPGA_REMOTE_SUDO-}"
TIMEOUT="${FPGA_TIMEOUT:-120}"
UART_MODE="${FPGA_UART_MODE:-ci}"
SESSION="${FPGA_UART_TMUX_SESSION:-fpga-uart}"
PASS="${FPGA_PASS_PATTERN-}"
FAIL="${FPGA_FAIL_PATTERN-}"
REMOTE_PAYLOAD="${FPGA_REMOTE_PAYLOAD-}"
KILL_READERS="${FPGA_KILL_UART_READERS:-0}"
RESET_ONLY=0
WORKER=0
PAYLOAD=""
usage() {
    printf '%s\n' \
        'Usage: scripts/fpga-run-ai.sh --payload <file> | --reset-only' \
        'FPGA_UART_MODE=ci|interactive; FPGA_PASS_PATTERN is literal; FPGA_FAIL_PATTERN is regex.' \
        'FPGA_TIMEOUT bounds observation, not workload completion. No automatic reader killing.' \
        'Supply exact FPGA_HOST/FPGA_LTX/FPGA_DRIVER/FPGA_XDMA_PROCESS paths.'
}
while (( $# )); do
    case "$1" in
        --payload) (( $# >= 2 )) || { usage >&2; exit 2; }; PAYLOAD="$2"; shift 2 ;;
        --reset-only) RESET_ONLY=1; shift ;;
        --interactive-worker) WORKER=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
fpga_positive FPGA_TIMEOUT "$TIMEOUT"
fpga_bool FPGA_KILL_UART_READERS "$KILL_READERS"
[[ "$KILL_READERS" == 0 ]] || {
    echo "error: automatic reader killing is unsupported; stop only your owned reader explicitly" >&2
    exit 2
}
[[ "$UART_MODE" == ci || "$UART_MODE" == interactive ]] || { echo "error: invalid FPGA_UART_MODE" >&2; exit 2; }
fpga_path FPGA_LTX "$LTX"
[[ "$RESET_ONLY" == 1 || -s "$PAYLOAD" ]] || { echo "error: nonempty --payload required" >&2; exit 2; }
[[ "$RESET_ONLY" == 0 || -z "$PAYLOAD" ]] || { echo "error: reset-only and payload are mutually exclusive" >&2; exit 2; }
[[ -z "$REMOTE_PAYLOAD" ]] || fpga_path FPGA_REMOTE_PAYLOAD "$REMOTE_PAYLOAD"
[[ -f "$SCRIPT_DIR/fpga/reset_cpu.tcl" ]]
for tool in ssh scp sha256sum; do command -v "$tool" >/dev/null; done
driver_cmd="$(fpga_tool_path "$DRIVER")"
loader_cmd="$(fpga_tool_path "$LOADER")"
if [[ -n "$FAIL" ]]; then
    regex_rc=0
    [[ "" =~ $FAIL ]] || regex_rc=$?
    (( regex_rc != 2 )) || { echo "error: invalid FAIL regex" >&2; exit 2; }
fi
UART_CMD="${FPGA_UART_CMD-}"
if [[ -z "$UART_CMD" ]]; then
    UART_CMD="${REMOTE_SUDO:+$REMOTE_SUDO }"' "$HOME"/xdma_work/tools/proto/pcie-util /dev/xdma0_user uart 0x10000'
fi

if [[ "$UART_MODE" == interactive && "$RESET_ONLY" == 0 && "$WORKER" == 0 ]]; then
    command -v tmux >/dev/null
    [[ "$SESSION" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "error: invalid tmux session" >&2; exit 2; }
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "error: existing tmux session preserved: $SESSION" >&2; exit 1
    fi
    # The worker owns the lease through the entire interactive session.
    command_args=(env "XS_PROJECT_ROOT=$XS_PROJECT_ROOT" "FPGA_HOST=$HOST"
        "FPGA_REMOTE_SETUP=$REMOTE_SETUP" "FPGA_LTX=$LTX" "FPGA_DRIVER=$DRIVER"
        "FPGA_XDMA_PROCESS=$LOADER" "FPGA_REMOTE_SUDO=$REMOTE_SUDO"
        "FPGA_UART_CMD=$UART_CMD" "FPGA_UART_MODE=interactive"
        "FPGA_TIMEOUT=$TIMEOUT" "FPGA_REMOTE_PAYLOAD=$REMOTE_PAYLOAD"
        "FPGA_KILL_UART_READERS=0" bash "$SCRIPT_DIR/fpga-run-ai.sh"
        --payload "$(realpath "$PAYLOAD")" --interactive-worker)
    printf -v command_text '%q ' "${command_args[@]}"
    tmux new-session -d -s "$SESSION" "$command_text"
    echo "[fpga] interactive worker started; attach with: tmux attach -t $SESSION"
    echo "[fpga] detached terminal is not a workload acceptance result"
    exit 0
fi

run_id="$(date +%Y%m%d-%H%M%S)-$$"
remote_tcl="/tmp/xsai-reset-${run_id}.tcl"
remote_temp=""
uploaded=0
remote_reset_log="/tmp/xsai-reset-${run_id}.log"
cleanup() {
    local rc=$?
    trap - EXIT
    if [[ "$uploaded" == 1 ]]; then
        fpga_remote "rm -f -- $(fpga_quote "$remote_tcl") $(fpga_quote "$remote_reset_log")" >/dev/null 2>&1 || true
    fi
    if [[ -n "$remote_temp" ]]; then
        fpga_remote "rm -f -- $(fpga_quote "$remote_temp")" >/dev/null 2>&1 || true
    fi
    fpga_release
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
fpga_acquire
fpga_remote "test -s $(fpga_quote "$LTX")"
if [[ "$RESET_ONLY" == 0 ]]; then
    fpga_remote "test -s $driver_cmd && test -x $loader_cmd"
    digest="$(sha256sum "$PAYLOAD" | awk '{print $1}')"
    REMOTE_PAYLOAD="${REMOTE_PAYLOAD:-/tmp/xsai-payload-${digest}.bin}"
    existing="$(fpga_remote "if test -f $(fpga_quote "$REMOTE_PAYLOAD"); then sha256sum -- $(fpga_quote "$REMOTE_PAYLOAD") | cut -d ' ' -f1; fi")"
    if [[ "$existing" == "$digest" ]]; then
        echo "[fpga] payload SHA256 matches; reusing $REMOTE_PAYLOAD"
    else
        remote_temp="${REMOTE_PAYLOAD}.upload-${run_id}"
        scp -- "$PAYLOAD" "$HOST:$remote_temp"
        fpga_remote "set -e; test $(fpga_quote "$digest") = \"\$(sha256sum -- $(fpga_quote "$remote_temp") | cut -d ' ' -f1)\"; mv -- $(fpga_quote "$remote_temp") $(fpga_quote "$REMOTE_PAYLOAD")"
        remote_temp=""
    fi
fi
scp -- "$SCRIPT_DIR/fpga/reset_cpu.tcl" "$HOST:$remote_tcl"
uploaded=1
reset() {
    fpga_remote_setup "vivado -mode batch -source $(fpga_quote "$remote_tcl") -tclargs $(fpga_quote "$LTX") $1"
}
reset 1
if [[ "$RESET_ONLY" == 1 ]]; then echo "[fpga] reset asserted"; exit 0; fi
[[ -z "${FPGA_PCIE_REMOVE_CMD:-}" ]] || fpga_remote "$FPGA_PCIE_REMOVE_CMD"
[[ -z "${FPGA_PCIE_RESCAN_CMD:-}" ]] || fpga_remote "$FPGA_PCIE_RESCAN_CMD"
fpga_remote "${REMOTE_SUDO:+$REMOTE_SUDO }$loader_cmd -i $(fpga_quote "$REMOTE_PAYLOAD") -d $driver_cmd"
mkdir -p "$XS_PROJECT_ROOT/log"
log_file="$XS_PROJECT_ROOT/log/fpga-uart-${run_id}.log"
reset_log="$XS_PROJECT_ROOT/log/fpga-reset-${run_id}.log"
if [[ "$UART_MODE" == interactive ]]; then
    reset 0 > "$reset_log" 2>&1
    echo "[fpga] interactive UART; exit this terminal to release the board lease"
    ssh -tt -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "bash -lc $(fpga_quote "$UART_CMD")"
    exit $?
fi
# Start the remote UART reader before releasing reset, so boot output is retained.
release_cmd="set -e; ${REMOTE_SETUP}; vivado -mode batch -source $(fpga_quote "$remote_tcl") -tclargs $(fpga_quote "$LTX") 0"
set +e
printf -v uart_args '%q ' "$UART_CMD" "$TIMEOUT" "$PASS" "$FAIL" "$release_cmd" "$remote_reset_log"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "bash -s -- $uart_args" <<'UART' | tee "$log_file"
set -euo pipefail
cmd="$1"; limit="$2"; pass="$3"; fail="$4"; release="$5"; reset_log="$6"
scratch="$(mktemp -d /tmp/xsai-uart.XXXXXXXX)"
mkfifo "$scratch/fifo"
child=""
cleanup_uart() {
    [[ -z "$child" ]] || kill -- "-$child" 2>/dev/null || true
    [[ -z "$child" ]] || kill -KILL -- "-$child" 2>/dev/null || true
    [[ -z "$child" ]] || wait "$child" 2>/dev/null || true
    rm -f -- "$scratch/fifo"
    rmdir -- "$scratch"
}
trap cleanup_uart EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
setsid bash -lc "$cmd" > "$scratch/fifo" 2>&1 &
child=$!
exec 3< "$scratch/fifo"
bash -lc "$release" > "$reset_log" 2>&1
deadline=$((SECONDS + limit))
while true; do
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || exit 124
    if IFS= read -r -t "$remaining" line <&3; then
        line="${line%$'\r'}"
        printf '%s\n' "$line"
        if [[ -n "$fail" && "$line" =~ $fail ]]; then exit 42; fi
        if [[ -n "$pass" && "$line" == *"$pass"* ]]; then exit 0; fi
    else
        status=$?
        (( status <= 128 )) || exit 124
        exit 3
    fi
done
UART
pipeline_status=("${PIPESTATUS[@]}")
uart_status="${pipeline_status[0]}"
scp -- "$HOST:$remote_reset_log" "$reset_log" >/dev/null 2>&1
set -e
[[ "${pipeline_status[1]}" == 0 ]] || { echo "error: UART log write failed" >&2; exit 1; }
case "$uart_status" in
    0) echo "[fpga] configured PASS marker observed" ;;
    42) echo "[fpga] configured FAIL marker observed" >&2; exit 1 ;;
    124) echo "[fpga] observation timeout; workload may still be running" >&2; exit 124 ;;
    3) echo "[fpga] UART ended without PASS; workload not verified" >&2; exit 3 ;;
    *) [[ ! -f "$reset_log" ]] || cat "$reset_log" >&2
       echo "[fpga] UART/reset failed: $uart_status" >&2; exit "$uart_status" ;;
esac
