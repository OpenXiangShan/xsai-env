#!/usr/bin/env bash
# update-submodule.sh
# Updates submodules listed in UPDATE_LIST by reading path/url/branch
# directly from .gitmodules. Edit .gitmodules to change targets.
#
# Usage:
#   bash scripts/update-submodule.sh           # update all in whitelist
#   bash scripts/update-submodule.sh NEMU XSAI # update specific ones

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── Whitelist ────────────────────────────────────────────────────────────────
# Names must match the submodule name (first field in [submodule "NAME"])
# Add/remove entries here to control what gets updated.
UPDATE_LIST=(
    XSAI
    NEMU
    nexus-am
    llvm-project-ame
    qemu
)

# Override whitelist with CLI args if provided
if [[ $# -gt 0 ]]; then
    UPDATE_LIST=("$@")
fi

# ── Helper: parse a field from .gitmodules for a given submodule name ────────
gitmodules_get() {
    local name="$1" field="$2"
    git config -f "$ROOT/.gitmodules" "submodule.${name}.${field}" 2>/dev/null || echo ""
}

# ── Update one submodule ─────────────────────────────────────────────────────
update_one() {
    local name="$1"
    local path branch shallow refspec

    path=$(gitmodules_get "$name" path)
    branch=$(gitmodules_get "$name" branch)
    shallow=$(gitmodules_get "$name" shallow)

    if [[ -z "$path" ]]; then
        echo "[update] WARNING: submodule '$name' not found in .gitmodules, skipping."
        return
    fi
    if [[ ! -e "$ROOT/$path/.git" ]]; then
        echo "[update] WARNING: submodule '$name' is not initialized, skipping."
        return
    fi

    local depth_flag=""
    [[ "$shallow" == "true" ]] && depth_flag="--depth=1"

    echo "[update] ── $name  (path=$path  branch=${branch:-(default)}  shallow=${shallow:-false})"

    cd "$ROOT/$path"

    if [[ -n "$branch" ]]; then
        refspec="+refs/heads/$branch:refs/remotes/origin/$branch"
        if git show-ref --verify --quiet "refs/heads/$branch"; then
            depth_flag=""
        fi
        git fetch $depth_flag origin "$refspec"
        if ! git config --fixed-value --get-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*' >/dev/null &&
           ! git config --fixed-value --get-all remote.origin.fetch "$refspec" >/dev/null; then
            git config --add remote.origin.fetch "$refspec"
        fi
        if git show-ref --verify --quiet "refs/heads/$branch"; then
            git checkout "$branch"
            git merge --ff-only "origin/$branch"
        else
            git checkout --track -b "$branch" "origin/$branch"
        fi
    else
        # No branch pinned: just update to whatever the parent repo has locked
        git fetch $depth_flag origin
    fi

    cd "$ROOT"
    echo "[update] ✓ $name"
}

# ── Main ─────────────────────────────────────────────────────────────────────
echo "[update] Updating submodules: ${UPDATE_LIST[*]}"
echo ""

for name in "${UPDATE_LIST[@]}"; do
    update_one "$name"
done

echo ""
echo "[update] Refreshing VERSIONS..."
bash "$ROOT/scripts/update-versions.sh"

echo "[update] Done."
