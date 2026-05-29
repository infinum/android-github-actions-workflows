#!/usr/bin/env bash
#
# gather-deps.sh — enumerate every module (root + included builds) and run
# the `dependencies` task on each, plus `buildEnvironment` on the root for the
# buildscript classpath.
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
ROOT_MODULES_FILE="$(dirname "$OUTPUT")/root-modules.txt"
INCLUDED_BUILDS_FILE="$(dirname "$OUTPUT")/included-builds.txt"
INCLUDED_MODULES_FILE="$(dirname "$OUTPUT")/included-modules.txt"

echo "==> Enumerating modules…"
PROJECTS_LOG="$(dirname "$OUTPUT")/gradle-projects.log"
if ! ./gradlew -q --console=plain projects > "$PROJECTS_LOG" 2>&1; then
    echo "    failed to enumerate modules; gradle output follows:" >&2
    cat "$PROJECTS_LOG" >&2
    exit 1
fi

grep -oE "Project ':[^']+'" "$PROJECTS_LOG" \
    | sed -E "s/Project '(.+)'/\1/" \
    | sort -u > "$ROOT_MODULES_FILE" || true

# Capture included build IDs (e.g. :build-logic) from `gradle projects` output.
grep -oE "Included build ':[^']+'" "$PROJECTS_LOG" \
    | sed -E "s/Included build '(.+)'/\1/" \
    | sort -u > "$INCLUDED_BUILDS_FILE" || true

TMP_INCLUDED_MODULES_FILE="$(dirname "$OUTPUT")/included-modules.raw.txt"
: > "$TMP_INCLUDED_MODULES_FILE"
while IFS= read -r included_build; do
    [ -z "$included_build" ] && continue
    INCLUDED_PROJECTS_LOG="$(dirname "$OUTPUT")/gradle-projects${included_build//:/_}.log"
    if ! ./gradlew -q --console=plain "${included_build}:projects" > "$INCLUDED_PROJECTS_LOG" 2>&1; then
        echo "    failed to enumerate modules for included build $included_build; gradle output follows:" >&2
        cat "$INCLUDED_PROJECTS_LOG" >&2
        exit 1
    fi

    # Depending on Gradle/composite setup, project paths may be emitted either
    # as ':' (relative to the included build) or already root-qualified.
    grep -oE "Project ':[^']*'" "$INCLUDED_PROJECTS_LOG" \
        | sed -E "s/Project '(.+)'/\1/" \
        | while IFS= read -r project_path; do
            if [ "$project_path" = ":" ]; then
                echo "$included_build"
            elif [[ "$project_path" == "$included_build" || "$project_path" == "$included_build":* ]]; then
                echo "$project_path"
            elif [ -n "$project_path" ]; then
                echo "${included_build}${project_path}"
            fi
        done >> "$TMP_INCLUDED_MODULES_FILE"
done < "$INCLUDED_BUILDS_FILE"

sort -u "$TMP_INCLUDED_MODULES_FILE" > "$INCLUDED_MODULES_FILE"
rm -f "$TMP_INCLUDED_MODULES_FILE"

cat "$ROOT_MODULES_FILE" "$INCLUDED_MODULES_FILE" | sed '/^$/d' | sort -u > "$MODULES_FILE"

MODULE_COUNT=$(wc -l < "$MODULES_FILE" | tr -d ' ')
ROOT_MODULE_COUNT=$(wc -l < "$ROOT_MODULES_FILE" | tr -d ' ')
INCLUDED_BUILD_COUNT=$(wc -l < "$INCLUDED_BUILDS_FILE" | tr -d ' ')
INCLUDED_MODULE_COUNT=$(wc -l < "$INCLUDED_MODULES_FILE" | tr -d ' ')
echo "    found $MODULE_COUNT modules (root: $ROOT_MODULE_COUNT, included builds: $INCLUDED_BUILD_COUNT, included modules: $INCLUDED_MODULE_COUNT) → $MODULES_FILE"
if [ "$MODULE_COUNT" -gt 0 ]; then
    echo "    modules:"
    sed 's/^/      - /' "$MODULES_FILE"
fi
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
