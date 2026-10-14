#!/usr/bin/env bash
# Stage fixed tools and explicitly named AOT outputs into a new directory.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=common.sh
source "$HERE/common.sh"

usage() {
    cat >&2 <<'EOF'
usage: stage.sh --dest STAGE [--bundle BUNDLE] [--abi cp312|cp313]
                [--object PATH[:relative/path]]
                [--file PATH:relative/path]

STAGE must not exist.  The bundle tools/libraries and the selected wheel are
copied; AOT objects/scripts are copied only when named explicitly.
EOF
}

bundle="${TRITON_XSCPU_BUNDLE:-}"
dest=
abi=cp313
objects=()
files=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bundle) [ "$#" -ge 2 ] || { usage; exit 2; }; bundle="$2"; shift 2 ;;
        --dest) [ "$#" -ge 2 ] || { usage; exit 2; }; dest="$2"; shift 2 ;;
        --abi) [ "$#" -ge 2 ] || { usage; exit 2; }; abi="$2"; shift 2 ;;
        --object) [ "$#" -ge 2 ] || { usage; exit 2; }; objects+=("$2"); shift 2 ;;
        --file) [ "$#" -ge 2 ] || { usage; exit 2; }; files+=("$2"); shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done

[ -n "$dest" ] || { usage; exit 2; }
case "$abi" in cp312|cp313) ;; *) triton_die "unsupported Python ABI: $abi" ;; esac
triton_fresh_dir "$dest"
TRITON_XSCPU_BUNDLE="$bundle" bundle="$(triton_bundle)"

mkdir -p "$dest/opt/triton-xscpu/xscpu-tools"
cp -a "$bundle/xscpu-tools/bin" "$dest/opt/triton-xscpu/xscpu-tools/"
cp -a "$bundle/xscpu-tools/lib" "$dest/opt/triton-xscpu/xscpu-tools/"
cp -a "$bundle/setup_xscpu_env.sh" "$dest/opt/triton-xscpu/"
cp -a "$bundle/install_xscpu.py" "$dest/opt/triton-xscpu/"
cp -a "$bundle/manifest.json" "$dest/opt/triton-xscpu/bundle-manifest.json"
[ -d "$bundle/bootstrap" ] ||
    triton_die "bundle bootstrap wheels are missing: $bundle/bootstrap"
cp -a "$bundle/bootstrap" "$dest/opt/triton-xscpu/"
[ -d "$bundle/licenses" ] && cp -a "$bundle/licenses" "$dest/opt/triton-xscpu/"
wheel="$(find "$bundle" -maxdepth 1 -type f -name "triton-*-${abi}-${abi}-linux_riscv64.whl" -print)"
[ "$(printf '%s\n' "$wheel" | sed '/^$/d' | wc -l)" -eq 1 ] ||
    triton_die "exactly one Triton $abi wheel is required in bundle"
triton_verify_artifact "$wheel" "triton-3.4.0+gitb758c587-${abi}-${abi}-linux_riscv64.whl"
mkdir -p "$dest/opt/triton-xscpu/wheels"
cp -a "$wheel" "$dest/opt/triton-xscpu/wheels/"

for spec in "${objects[@]}"; do
    src="${spec%%:*}"
    rel="${spec#*:}"
    [ "$src" != "$rel" ] || rel="$(basename -- "$src")"
    triton_relative_path "$rel"
    triton_require_file "$src"
    mkdir -p "$dest/opt/triton-xscpu/objects/$(dirname -- "$rel")"
    cp -a "$src" "$dest/opt/triton-xscpu/objects/$rel"
done

for spec in "${files[@]}"; do
    src="${spec%%:*}"
    rel="${spec#*:}"
    [ "$src" != "$rel" ] || triton_die "--file requires PATH:relative/path: $spec"
    triton_relative_path "$rel"
    triton_require_file "$src"
    mkdir -p "$dest/opt/triton-xscpu/files/$(dirname -- "$rel")"
    cp -a "$src" "$dest/opt/triton-xscpu/files/$rel"
done

cp -a "$HERE/manifest.json" "$dest/opt/triton-xscpu/integration-manifest.json"
cp -a "$HERE/PROVENANCE.md" "$dest/opt/triton-xscpu/"
printf 'triton-xscpu: staged %s\n' "$dest"
