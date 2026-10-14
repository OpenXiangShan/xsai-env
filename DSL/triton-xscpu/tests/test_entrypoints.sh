#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "$HERE/.." && pwd -P)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

expect_fail() {
    if "$@" >"$tmp/stdout" 2>"$tmp/stderr"; then
        echo "expected failure: $*" >&2
        exit 1
    fi
}

expect_fail "$ROOT/compile.sh" --driver "$tmp/no.py" --output "$tmp/out.o" \
    --cache-dir "$tmp/cache"
grep -q -- 'required input is missing' "$tmp/stderr"

expect_fail "$ROOT/compile.sh" --driver "$tmp/no.py" --output "$tmp/out.o"
grep -q -- '--cache-dir is required' "$tmp/stderr"

touch "$tmp/existing.o"
touch "$tmp/driver.py"
expect_fail "$ROOT/compile.sh" --driver "$tmp/driver.py" --output "$tmp/existing.o" \
    --cache-dir "$tmp/cache"
grep -q -- 'stale artifact guard' "$tmp/stderr"

mkdir "$tmp/stage"
expect_fail "$ROOT/stage.sh" --dest "$tmp/stage"
grep -q -- 'stale artifact guard' "$tmp/stderr"

expect_fail "$ROOT/stage.sh" --dest "$tmp/new-stage" --bundle "$tmp/no-bundle"
grep -q -- 'bundle directory does not exist' "$tmp/stderr"

mkdir -p "$tmp/incomplete/xscpu-tools/bin" "$tmp/incomplete/xscpu-tools/lib"
touch "$tmp/incomplete/manifest.json" "$tmp/incomplete/setup_xscpu_env.sh"
expect_fail "$ROOT/stage.sh" --dest "$tmp/missing-tool-stage" \
    --bundle "$tmp/incomplete"
grep -q -- 'required executable is missing' "$tmp/stderr"

echo "triton-xscpu entrypoint negative tests: PASS"
