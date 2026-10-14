#!/usr/bin/env bash
# Shared SSH quoting and cooperative board ownership. Source from FPGA helpers.
fpga_quote() { printf '%q' "$1"; }
fpga_remote() {
    ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" "bash -lc $(fpga_quote "$1")"
}
fpga_remote_setup() { fpga_remote "set -e; ${REMOTE_SETUP}; $1"; }
fpga_bool() {
    [[ "$2" == 0 || "$2" == 1 ]] || {
        echo "error: $1 must be 0 or 1" >&2; return 2;
    }
}
fpga_positive() {
    [[ "$2" =~ ^[1-9][0-9]*$ ]] || {
        echo "error: $1 must be a positive integer" >&2; return 2;
    }
}
fpga_path() {
    [[ "$2" == /* && "$2" != / && "$2" != *$'\n'* ]] || {
        echo "error: $1 must be an explicit absolute path" >&2; return 2;
    }
}
fpga_tool_path() {
    case "$1" in
        '~/'*) printf '"$HOME"/%s' "$(fpga_quote "${1:2}")" ;;
        /*) fpga_quote "$1" ;;
        *) echo "error: remote tool needs absolute or ~/ path: $1" >&2; return 2 ;;
    esac
}
fpga_acquire() {
    [[ "$HOST" != -* && "$HOST" != *[[:space:]]* && -n "$HOST" ]] || {
        echo "error: invalid FPGA_HOST" >&2; return 2;
    }
    local command='set -e; mkdir -p "$HOME/.cache/xsai-env"; exec flock -n "$HOME/.cache/xsai-env/fpga-board.lock" bash -c '\''printf "XSAI_LOCK_READY\n"; cat >/dev/null'\'''
    coproc FPGA_LEASE { fpga_remote "$command"; }
    FPGA_LEASE_PID_SAVED="$FPGA_LEASE_PID"
    FPGA_LEASE_INPUT="${FPGA_LEASE[1]}"
    local ready
    if ! IFS= read -r -t 20 ready <&"${FPGA_LEASE[0]}" || [[ "$ready" != XSAI_LOCK_READY ]]; then
        echo "error: FPGA board lease unavailable; refusing hardware mutation" >&2
        fpga_release
        return 1
    fi
    # Cooperative leases cannot account for legacy/manual device users.
    local user_status=0
    fpga_remote "pgrep -fa '[p]cie-util .*uart|[x]dma_process|[v]ivado.*(-mode| -source)'" || user_status=$?
    if [[ "$user_status" == 0 ]]; then
        echo "error: existing UART/XDMA/Vivado user; refusing reset/load" >&2
        fpga_release
        return 1
    fi
    if [[ "$user_status" != 1 ]]; then
        echo "error: cannot establish board-user state" >&2
        fpga_release
        return 1
    fi
}
fpga_release() {
    if [[ -n "${FPGA_LEASE_INPUT:-}" ]]; then
        exec {FPGA_LEASE_INPUT}>&- || true
        FPGA_LEASE_INPUT=""
    fi
    if [[ -n "${FPGA_LEASE_PID_SAVED:-}" ]]; then
        kill "$FPGA_LEASE_PID_SAVED" 2>/dev/null || true
        wait "$FPGA_LEASE_PID_SAVED" 2>/dev/null || true
        FPGA_LEASE_PID_SAVED=""
    fi
}
