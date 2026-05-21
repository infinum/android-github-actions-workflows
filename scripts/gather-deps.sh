#!/usr/bin/env bash
#
# gather-deps.sh — enumerate every module and run the `dependencies` task
# on each, plus `buildEnvironment` on the root for the buildscript classpath.
# Produces a single text file ready for downstream parsing.
#
# Usage:
#   gather-deps.sh [project-dir] [output-file]
#
# Defaults:
#   project-dir  → current working directory
#   output-file  → ./build/dependabot-tools/gather-deps.txt
#
set -euo pipefail

PROJECT_DIR=${1:-.}
OUTPUT=${2:-build/dependabot-tools/gather-deps.txt}

cd "$PROJECT_DIR"
mkdir -p "$(dirname "$OUTPUT")"

MODULES_FILE="$(dirname "$OUTPUT")/modules.txt"

echo "==> Enumerating modules…"
./gradlew -q --console=plain projects 2>/dev/null \
    | grep -oE "Project ':[^']+'" \
    | sed -E "s/Project '(.+)'/\1/" \
    | sort -u > "$MODULES_FILE"

MODULE_COUNT=$(wc -l < "$MODULES_FILE" | tr -d ' ')
echo "    found $MODULE_COUNT modules → $MODULES_FILE"

echo "==> Building task list…"
TASKS="buildEnvironment"
while IFS= read -r module; do
    TASKS="$TASKS ${module}:dependencies"
done < "$MODULES_FILE"

echo "==> Running gradle…"
# shellcheck disable=SC2086
./gradlew --console=plain $TASKS > "$OUTPUT" 2>&1 || {
    echo "    gradle exited non-zero; output preserved at $OUTPUT" >&2
    exit 1
}
LINES=$(wc -l < "$OUTPUT" | tr -d ' ')
echo "    saved to $OUTPUT ($LINES lines)"
