#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NUTSHELL_DIR="$ROOT/NutShell"

if [[ -f "$NUTSHELL_DIR/Makefile" ]]; then
  exit 0
fi

echo "[test] NutShell is required by make test; initializing it now."
echo "[test] This explicitly enables checkout for the pinned test dependency."

if ! git -c submodule.NutShell.update=checkout \
  submodule update --init --checkout NutShell; then
  echo "[test] Failed to initialize required NutShell." >&2
  echo "[test] Retry with: git submodule update --init --checkout NutShell" >&2
  exit 1
fi

if [[ ! -f "$NUTSHELL_DIR/Makefile" ]]; then
  echo "[test] NutShell initialization completed without a usable Makefile." >&2
  echo "[test] Check the submodule URL and the pinned commit, then retry." >&2
  exit 1
fi
