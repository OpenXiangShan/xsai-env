#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GIT_FORCE_INIT="${GIT_FORCE_INIT:-0}"
INIT_OPTIONAL_SUBMODULES="${INIT_OPTIONAL_SUBMODULES:-0}"
case "$INIT_OPTIONAL_SUBMODULES" in
  0|1) ;;
  *)
    echo "[setup] INIT_OPTIONAL_SUBMODULES must be 0 or 1." >&2
    exit 2
    ;;
esac

FORCE_ARGS=()
if [[ "$GIT_FORCE_INIT" == "1" ]]; then
  FORCE_ARGS=(--force)
fi

init_optional_source() {
  local module="$1"
  shift
  local log_file="$ROOT/log/setup/$module.log"
  mkdir -p "$(dirname "$log_file")"
  echo "[setup] Trying optional source: $module"
  # These repositories may still require access. Do not open a credential
  # prompt or flood the terminal with Git's clone retries on failure.
  if GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false GCM_INTERACTIVE=never \
    git submodule update --init --checkout "${FORCE_ARGS[@]}" "$@" "$module" \
    >"$log_file" 2>&1; then
    echo "[setup] Optional source ready: $module"
  else
    echo "[setup] Skipped optional source: $module (access or network unavailable)."
    echo "[setup] Required components are initialized; full Git log: $log_file"
  fi
}

init_optional_sources() {
  if [[ "$INIT_OPTIONAL_SUBMODULES" == "1" ]]; then
    init_optional_source llvm-project-ame --depth 1
    init_optional_source riscv-matrix-spec
  else
    echo "[setup] Skipping optional sources: llvm-project-ame and riscv-matrix-spec."
    echo "[setup] They are not required for normal software/simulator setup."
    echo "[setup] Source developers with access can use: make init-force INIT_OPTIONAL_SUBMODULES=1"
  fi
  echo "[setup] AME programs need an AME compiler, not its source checkout."
  echo "[setup] Use the prebuilt package: README.md -> Getting AME LLVM."
}

init_dev() {
  git submodule update --init "${FORCE_ARGS[@]}" DRAMsim3 NEMU NutShell nexus-am qemu
  git submodule update --init "${FORCE_ARGS[@]}" XSAI
  "$(command -v make)" -C XSAI init-force
  "$(command -v make)" -C firmware init-force
  init_optional_sources
}

init_user() {
  git submodule update --init "${FORCE_ARGS[@]}" qemu
  "$(command -v make)" -C firmware init GIT_FORCE_INIT="$GIT_FORCE_INIT"
}

case "${1:-dev}" in
  dev)
    init_dev
    ;;
  user)
    init_user
    ;;
  *)
    echo "Usage: $0 [dev|user]" >&2
    exit 1
    ;;
esac

source "$ROOT/env.sh"
echo XS_PROJECT_ROOT: ${XS_PROJECT_ROOT}
echo NEMU_HOME: ${NEMU_HOME}
echo AM_HOME: ${AM_HOME}
echo NOOP_HOME: ${NOOP_HOME}
