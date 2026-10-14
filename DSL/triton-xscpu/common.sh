#!/usr/bin/env bash
# Shared checks for the portable Triton/xscpu entrypoints.
set -euo pipefail
TRITON_INTEGRATION_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

triton_die() {
    printf 'triton-xscpu: %s\n' "$*" >&2
    exit 2
}

triton_require_file() {
    [ -f "$1" ] || triton_die "required input is missing: $1"
}

triton_require_exec() {
    [ -x "$1" ] || triton_die "required executable is missing or not executable: $1"
}

triton_bundle() {
    local bundle="${TRITON_XSCPU_BUNDLE:-}"
    [ -n "$bundle" ] || triton_die \
        'set TRITON_XSCPU_BUNDLE to an extracted triton-xscpu-riscv64-20260918 bundle'
    [ -d "$bundle" ] || triton_die "bundle directory does not exist: $bundle"
    command -v python3 >/dev/null 2>&1 ||
        triton_die 'python3 is required to read the integration manifest and verify hashes'
    triton_require_file "$bundle/manifest.json"
    triton_require_file "$bundle/setup_xscpu_env.sh"
    for tool in triton-shared-opt buddy-opt buddy-translate buddy-llc buddy-llvm-objdump; do
        triton_require_exec "$bundle/xscpu-tools/bin/$tool"
        triton_verify_artifact "$bundle/xscpu-tools/bin/$tool" "xscpu-tools/bin/$tool"
    done
    triton_verify_bundle_manifest "$bundle"
    if [ -n "${TRITON_XSCPU_ARCHIVE:-}" ]; then
        triton_verify_archive "$TRITON_XSCPU_ARCHIVE"
    fi
    printf '%s\n' "$bundle"
}

triton_verify_archive() {
    local archive="$1" expected actual
    triton_require_file "$archive"
    expected="$(python3 - "$TRITON_INTEGRATION_DIR/manifest.json" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data["sources"]["triton-xscpu-bundle"]["archive_sha256"])
PY
)"
    actual="$(triton_sha256 "$archive")"
    [ "$actual" = "$expected" ] || triton_die \
        "archive sha256 mismatch: expected $expected, got $actual"
}

triton_verify_bundle_manifest() {
    local bundle="$1"
    python3 - "$bundle" "$TRITON_INTEGRATION_DIR/manifest.json" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

bundle = Path(sys.argv[1])
integration = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
record = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
if record.get("name") != "triton-xscpu-riscv64-20260918":
    raise SystemExit("bundle manifest name is not the pinned release")

def check(rel, expected):
    path = bundle / rel
    if not path.is_file():
        raise SystemExit(f"bundle artifact is missing: {rel}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"bundle artifact hash mismatch: {rel}")

for tool in record.get("compiler_tools", []):
    rel = f"xscpu-tools/bin/{tool['name']}"
    check(rel, tool["sha256"])
    path = bundle / rel
    if path.stat().st_size != tool["bytes"]:
        raise SystemExit(f"bundle artifact size mismatch: {rel}")

for wheel in record.get("wheels", []):
    check(wheel["file"], wheel["sha256"])
for item in record.get("bootstrap", []):
    check(item["file"], item["sha256"])
    for name in record.get("runtime_libraries", []):
        check(f"xscpu-tools/lib/{name}", integration["artifacts"][f"runtime/{name}"]["sha256"])
check("manifest.json", integration["artifacts"]["bundle/manifest.json"]["sha256"])
check("setup_xscpu_env.sh", integration["artifacts"]["bundle/setup_xscpu_env.sh"]["sha256"])
check("install_xscpu.py", integration["artifacts"]["bundle/install_xscpu.py"]["sha256"])
PY
}

triton_fresh_output() {
    local path="$1"
    [ ! -e "$path" ] && [ ! -L "$path" ] ||
        triton_die "refusing to overwrite existing output (stale artifact guard): $path"
}

triton_fresh_dir() {
    local path="$1"
    [ ! -e "$path" ] && [ ! -L "$path" ] ||
        triton_die "refusing to reuse existing stage directory (stale artifact guard): $path"
}

triton_relative_path() {
    local path="$1"
    case "$path" in
        ""|/*|..|../*|*/../*|*/..)
            triton_die "destination path must be relative and stay inside stage: $path"
            ;;
    esac
}

triton_sha256() {
    sha256sum "$1" | awk '{print $1}'
}

triton_expected_sha() {
    local relative="$1"
    python3 - "$TRITON_INTEGRATION_DIR/manifest.json" "$relative" <<'PY'
import json
import sys

manifest, relative = sys.argv[1:]
data = json.load(open(manifest, encoding="utf-8"))
for artifact in data.get("artifacts", {}).values():
    if artifact.get("path") == relative:
        print(artifact["sha256"])
        break
else:
    raise SystemExit(f"artifact is not pinned in integration manifest: {relative}")
PY
}

triton_verify_artifact() {
    local path="$1"
    local relative="$2"
    local expected actual
    triton_require_file "$path"
    expected="$(triton_expected_sha "$relative")"
    actual="$(triton_sha256 "$path")"
    [ "$actual" = "$expected" ] || triton_die \
        "sha256 mismatch for $relative: expected $expected, got $actual"
}
