#!/usr/bin/env bash
# Run a user-supplied Triton AOT driver with the fixed xscpu bundle.
#
# This wrapper intentionally does not invent a backend build.  The driver is
# the source-level input and must create the requested object itself.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$HERE/common.sh"

usage() {
    cat >&2 <<'EOF'
usage: compile.sh --driver DRIVER.py --output OBJECT --cache-dir DIR
                  [--bundle BUNDLE] [--python PYTHON] [-- DRIVER_ARGS...]

The driver runs with XSCPU_BUNDLE_ROOT, TRITON_XSCPU_OUTPUT, and
TRITON_CACHE_DIR exported.  It must create OBJECT; existing OBJECTs and
non-empty cache directories are rejected.
EOF
}

bundle="${TRITON_XSCPU_BUNDLE:-}"
python="${PYTHON:-python3}"
driver=
output=
cache=

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bundle) [ "$#" -ge 2 ] || { usage; exit 2; }; bundle="$2"; shift 2 ;;
        --python) [ "$#" -ge 2 ] || { usage; exit 2; }; python="$2"; shift 2 ;;
        --driver) [ "$#" -ge 2 ] || { usage; exit 2; }; driver="$2"; shift 2 ;;
        --output) [ "$#" -ge 2 ] || { usage; exit 2; }; output="$2"; shift 2 ;;
        --cache-dir) [ "$#" -ge 2 ] || { usage; exit 2; }; cache="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --) shift; break ;;
        *) usage; exit 2 ;;
    esac
done

[ -n "$driver" ] || { usage; exit 2; }
[ -n "$output" ] || { usage; exit 2; }
[ -n "$cache" ] || triton_die \
    '--cache-dir is required; choose a fresh persistent directory, not an implicit /tmp cache'
triton_require_file "$driver"
triton_fresh_output "$output"
[ ! -e "$cache" ] || triton_die \
    "refusing to reuse existing cache directory (stale IR guard): $cache"

TRITON_XSCPU_BUNDLE="$bundle" bundle="$(triton_bundle)"
triton_fresh_dir "$cache"
mkdir -p "$cache"

if ! command -v -- "$python" >/dev/null 2>&1; then
    triton_die "Python executable is not available: $python"
fi

# The bundle setup script performs its own target/ABI checks.  It must be
# sourced with the same interpreter that runs the driver.
export TRITON_XSCPU_BUNDLE="$bundle"
export TRITON_XSCPU_OUTPUT="$(cd -- "$(dirname -- "$output")" && pwd -P)/$(basename -- "$output")"
export TRITON_CACHE_DIR="$(cd -- "$cache" && pwd -P)"
export PYTHONHASHSEED=0
export LC_ALL=C
export TZ=UTC
export PYTHON="$python"
source "$bundle/setup_xscpu_env.sh"

triton_fresh_output "$TRITON_XSCPU_OUTPUT"
"$python" "$driver" "$@"
[ -s "$TRITON_XSCPU_OUTPUT" ] ||
    triton_die "driver completed without creating a non-empty output: $TRITON_XSCPU_OUTPUT"
printf 'triton-xscpu: compiled %s\n' "$TRITON_XSCPU_OUTPUT"
