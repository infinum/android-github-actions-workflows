#!/usr/bin/env bash
#
# discover-dokka-modules.sh — list Dokka module directories inside a docs
# output directory.
#
# Dokka's multi-module HTML output puts each module's API docs in its own
# subdirectory (each containing an index.html), alongside a handful of
# shared asset directories that are not modules. This prints one module
# directory name per line, sorted, excluding those asset directories.
# Prints nothing (and exits 0) if the directory is missing, empty, or has
# no module subdirectories.
#
# Usage:
#   discover-dokka-modules.sh docs/
#
set -euo pipefail

DOCS_DIR="${1:-}"

EXCLUDED=("styles" "images" "scripts" "ui-kit" "fonts")

is_excluded() {
  local name="$1"
  local excluded
  for excluded in "${EXCLUDED[@]}"; do
    if [ "$name" = "$excluded" ]; then
      return 0
    fi
  done
  return 1
}

if [ -z "$DOCS_DIR" ] || [ ! -d "$DOCS_DIR" ]; then
  exit 0
fi

for entry in "$DOCS_DIR"/*/; do
  [ -d "$entry" ] || continue
  name="$(basename "$entry")"
  if is_excluded "$name"; then
    continue
  fi
  if [ -f "$entry/index.html" ]; then
    printf '%s\n' "$name"
  fi
done | sort
