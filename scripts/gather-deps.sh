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
PROJECTS_LOG="$(dirname "$OUTPUT")/gradle-projects.log"
if ! ./gradlew -q --console=plain projects > "$PROJECTS_LOG" 2>&1; then
    echo "    failed to enumerate modules; gradle output follows:" >&2
    cat "$PROJECTS_LOG" >&2
    exit 1
fi

grep -oE "Project ':[^']+'" "$PROJECTS_LOG" \
    | sed -E "s/Project '(.+)'/\1/" \
    | sort -u > "$MODULES_FILE" || true

MODULE_COUNT=$(wc -l < "$MODULES_FILE" | tr -d ' ')
echo "    found $MODULE_COUNT modules → $MODULES_FILE"
if [ "$MODULE_COUNT" -eq 0 ]; then
    echo "    no subprojects detected; only root buildscript dependencies will be captured"
fi

echo "==> Building task list…"
TASKS=(buildEnvironment)
while IFS= read -r module; do
    TASKS+=("${module}:dependencies")
done < "$MODULES_FILE"

echo "==> Running gradle…"
./gradlew --console=plain "${TASKS[@]}" > "$OUTPUT" 2>&1 || {
    echo "    gradle exited non-zero; output preserved at $OUTPUT" >&2
    exit 1
}
LINES=$(wc -l < "$OUTPUT" | tr -d ' ')
echo "    saved to $OUTPUT ($LINES lines)"
