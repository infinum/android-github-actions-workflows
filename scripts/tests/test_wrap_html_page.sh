#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/wrap-html-page.sh"
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

FRAGMENT='<p>Body fragment marker XYZZY with <strong>bold</strong> text.</p>'

# --- Basic page: title, heading, fragment passthrough, doctype.
BASIC="$(printf '%s' "$FRAGMENT" | bash "$SCRIPT" --title "My Title")"

check "title appears in <title>" "$BASIC" "<title>My Title</title>"
check "title appears as a heading" "$BASIC" "<h1>My Title</h1>"
check "body fragment is passed through intact" "$BASIC" "$FRAGMENT"

FIRST_LINE="$(printf '%s\n' "$BASIC" | head -1)"
assert_eq "output starts with <!DOCTYPE html>" "<!DOCTYPE html>" "$FIRST_LINE"

# --- No external network-fetched assets anywhere in the output.
if printf '%s' "$BASIC" | grep -Eq 'https?://'; then
  echo "FAIL - no http(s) asset references: found one"
  FAILURES=$((FAILURES + 1))
else
  echo "ok   - no http(s) asset references"
fi

# --- --active marks exactly one nav item as current.
ACTIVE_OUT="$(printf '%s' "$FRAGMENT" | bash "$SCRIPT" --title "Changelog" --active changelog --api-href kotlin/index.html)"
CURRENT_COUNT="$(printf '%s' "$ACTIVE_OUT" | grep -o 'aria-current="page"' | wc -l | tr -d ' ')"
assert_eq "--active marks exactly one nav item" "1" "$CURRENT_COUNT"
check "the active item is the one requested" "$ACTIVE_OUT" 'href="changelog.html" class="active" aria-current="page"'

# --- Omitting --api-href omits the API reference nav item entirely.
NO_API_OUT="$(printf '%s' "$FRAGMENT" | bash "$SCRIPT" --title "Overview")"
refute "omitting --api-href drops the nav item" "$NO_API_OUT" "API reference"

# --- Providing --api-href includes the nav item.
WITH_API_OUT="$(printf '%s' "$FRAGMENT" | bash "$SCRIPT" --title "Overview" --api-href kotlin/index.html)"
check "providing --api-href includes the nav item" "$WITH_API_OUT" "API reference"
check "the API reference href is passed through" "$WITH_API_OUT" 'href="kotlin/index.html"'

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all wrap-html-page tests passed"
