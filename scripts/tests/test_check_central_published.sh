#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/check-central-published.sh"
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

# Stub curl: emits an HTTP status code on stdout (as the script's
# `-w '%{http_code}'` would), keyed off which list the requested URL is in.
#   - PRESENT_FILE   -> 200
#   - REDIRECT_FILE  -> 302 (regression case: a redirect must not read as "found")
#   - FAIL_FILE      -> exits non-zero, prints nothing (transport failure)
#   - anything else  -> 404
mkdir -p "$TMP_DIR/bin"
cat > "$TMP_DIR/bin/curl" <<'EOF'
#!/usr/bin/env bash
url="${@: -1}"
if grep -Fxq "$url" "$FAIL_FILE" 2>/dev/null; then
  exit 7
fi
if grep -Fxq "$url" "$REDIRECT_FILE" 2>/dev/null; then
  echo "302"
  exit 0
fi
if grep -Fxq "$url" "$PRESENT_FILE" 2>/dev/null; then
  echo "200"
else
  echo "404"
fi
exit 0
EOF
chmod +x "$TMP_DIR/bin/curl"

export PATH="$TMP_DIR/bin:$PATH"
export PRESENT_FILE="$TMP_DIR/present.txt"
export REDIRECT_FILE="$TMP_DIR/redirect.txt"
export FAIL_FILE="$TMP_DIR/fail.txt"
export MAVEN_CENTRAL_BASE_URL="https://repo.example/maven2"

FAILURES=0
assert_published() {
  local name="$1" expected="$2"; shift 2
  local output
  output="$(bash "$SCRIPT" "$@")"
  if [ "$output" = "published=$expected" ]; then
    echo "ok   - $name"
  else
    echo "FAIL - $name: expected published=$expected, got '$output'"
    FAILURES=$((FAILURES + 1))
  fi
}

: > "$PRESENT_FILE"
: > "$REDIRECT_FILE"
: > "$FAIL_FILE"

assert_published "absent artifact reports false" "false" \
  com.infinum.android.common 0.3.0 kotlin

echo "https://repo.example/maven2/com/infinum/android/common/kotlin/0.2.0/kotlin-0.2.0.pom" > "$PRESENT_FILE"
assert_published "present artifact reports true" "true" \
  com.infinum.android.common 0.2.0 kotlin

assert_published "group dots become path separators" "false" \
  com.infinum.android.common 0.9.9 kotlin

cat > "$PRESENT_FILE" <<'EOF'
https://repo.example/maven2/com/infinum/android/common/kotlin/0.2.0/kotlin-0.2.0.pom
https://repo.example/maven2/com/infinum/android/common/android/0.2.0/android-0.2.0.pom
EOF
assert_published "all artifacts present reports true" "true" \
  com.infinum.android.common 0.2.0 kotlin android

assert_published "one missing artifact reports false" "false" \
  com.infinum.android.common 0.2.0 kotlin android view

if ! bash "$SCRIPT" com.infinum.android.common 0.2.0 >/dev/null 2>&1; then
  echo "ok   - missing artifact list is rejected"
else
  echo "FAIL - missing artifact list should exit non-zero"
  FAILURES=$((FAILURES + 1))
fi

: > "$PRESENT_FILE"
echo "https://repo.example/maven2/com/infinum/android/common/kotlin/0.4.0/kotlin-0.4.0.pom" > "$REDIRECT_FILE"
assert_published "a 3xx redirect does not count as present" "false" \
  com.infinum.android.common 0.4.0 kotlin

: > "$REDIRECT_FILE"
echo "https://repo.example/maven2/com/infinum/android/common/kotlin/0.5.0/kotlin-0.5.0.pom" > "$FAIL_FILE"
assert_published "a transport failure reports false, not an abort" "false" \
  com.infinum.android.common 0.5.0 kotlin

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all check-central-published tests passed"
