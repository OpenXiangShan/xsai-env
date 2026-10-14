#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "$#" == 2 && "$1" == --payload && -s "$2" ]] || {
    echo "usage: $0 --payload <nonempty payload>" >&2; exit 2
}
result="$(mktemp)"
trap 'rm -f "$result"' EXIT
FPGA_PROGRAM_RESULT_FILE="$result" bash "$script_dir/fpga-program-bitstream.sh"
IFS= read -r ltx < "$result"
[[ "$ltx" == /* && "$ltx" == *.ltx ]] || { echo "error: no verified programmed LTX result" >&2; exit 1; }
FPGA_LTX="$ltx" bash "$script_dir/fpga-run-ai.sh" --payload "$2"
