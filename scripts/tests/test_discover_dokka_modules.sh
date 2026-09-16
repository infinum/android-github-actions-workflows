#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/discover-dokka-modules.sh"
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

FAILURES=0

check() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -Fq -- "$needle"; then
    echo "ok   - $name"
  else
    echo "FAIL - $name: expected to find '$needle'"
    FAILURES=$((FAILURES + 1))
  fi
}

refute() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -Fq -- "$needle"; then
    echo "FAIL - $name: did not expect '$needle'"
    FAILURES=$((FAILURES + 1))
  else
    echo "ok   - $name"
  fi
}

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "ok   - $name"
  else
    echo "FAIL - $name: expected '$expected', got '$actual'"
    FAILURES=$((FAILURES + 1))
  fi
}

# --- Fixture: a docs dir with a module, Dokka asset dirs, and a
# subdirectory that lacks an index.html.
DOCS="$TMP_DIR/docs"
mkdir -p "$DOCS/kotlin" "$DOCS/styles" "$DOCS/images" "$DOCS/scripts" \
  "$DOCS/ui-kit" "$DOCS/fonts" "$DOCS/no-index"
touch "$DOCS/kotlin/index.html"
touch "$DOCS/styles/index.html"
touch "$DOCS/images/index.html"
touch "$DOCS/scripts/index.html"
touch "$DOCS/ui-kit/index.html"
touch "$DOCS/fonts/index.html"
touch "$DOCS/no-index/other.html"

OUTPUT="$(bash "$SCRIPT" "$DOCS")"

check "finds the module directory" "$OUTPUT" "kotlin"
refute "excludes styles" "$OUTPUT" "styles"
refute "excludes images" "$OUTPUT" "images"
refute "excludes scripts asset dir" "$OUTPUT" "scripts"
refute "excludes ui-kit" "$OUTPUT" "ui-kit"
refute "excludes fonts" "$OUTPUT" "fonts"
refute "ignores subdirectories without index.html" "$OUTPUT" "no-index"

LINE_COUNT="$(printf '%s\n' "$OUTPUT" | grep -c .)"
assert_eq "prints exactly one module line" "1" "$LINE_COUNT"

# --- Multiple modules come back sorted.
MULTI="$TMP_DIR/multidocs"
mkdir -p "$MULTI/zeta" "$MULTI/alpha"
touch "$MULTI/zeta/index.html" "$MULTI/alpha/index.html"
MULTI_OUTPUT="$(bash "$SCRIPT" "$MULTI")"
EXPECTED_SORTED="$(printf 'alpha\nzeta')"
assert_eq "modules are sorted" "$EXPECTED_SORTED" "$MULTI_OUTPUT"

# --- Empty directory produces no output and exits 0.
EMPTY="$TMP_DIR/emptydocs"
mkdir -p "$EMPTY"
EMPTY_OUTPUT="$(bash "$SCRIPT" "$EMPTY")"
EMPTY_STATUS=0
bash "$SCRIPT" "$EMPTY" >/dev/null || EMPTY_STATUS=$?
assert_eq "empty directory produces no output" "" "$EMPTY_OUTPUT"
assert_eq "empty directory exits 0" "0" "$EMPTY_STATUS"

# --- Missing directory produces no output and exits 0.
MISSING="$TMP_DIR/does-not-exist"
MISSING_OUTPUT="$(bash "$SCRIPT" "$MISSING")"
MISSING_STATUS=0
bash "$SCRIPT" "$MISSING" >/dev/null || MISSING_STATUS=$?
assert_eq "missing directory produces no output" "" "$MISSING_OUTPUT"
assert_eq "missing directory exits 0" "0" "$MISSING_STATUS"

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all discover-dokka-modules tests passed"
