#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/render-changelog.sh"
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

INPUT='[
  {"tag_name":"v0.3.0","draft":false,"body":"### Changes\n- Something new"},
  {"tag_name":"v0.2.0","draft":false,"body":"### Changes\n- Something older"},
  {"tag_name":"v9.9.9","draft":true,"body":"unreleased"}
]'

OUTPUT="$(printf '%s' "$INPUT" | bash "$SCRIPT")"

check "renders the newest release heading" "$OUTPUT" "## v0.3.0"
check "renders the older release heading" "$OUTPUT" "## v0.2.0"
check "renders release bodies" "$OUTPUT" "- Something new"
refute "excludes drafts" "$OUTPUT" "v9.9.9"

FIRST_HEADING="$(printf '%s' "$OUTPUT" | grep '^## ' | head -1)"
if [ "$FIRST_HEADING" = "## v0.3.0" ]; then
  echo "ok   - newest release comes first"
else
  echo "FAIL - newest release should come first, got '$FIRST_HEADING'"
  FAILURES=$((FAILURES + 1))
fi

EMPTY_OUTPUT="$(printf '[]' | bash "$SCRIPT")"
check "empty release list still renders a title" "$EMPTY_OUTPUT" "# Changelog"

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all render-changelog tests passed"
