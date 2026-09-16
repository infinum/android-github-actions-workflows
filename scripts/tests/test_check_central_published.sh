#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/check-central-published.sh"
TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

# Stub curl: succeeds only for URLs listed in $TMP_DIR/present.txt
mkdir -p "$TMP_DIR/bin"
cat > "$TMP_DIR/bin/curl" <<'EOF'
#!/usr/bin/env bash
url="${@: -1}"
grep -Fxq "$url" "$PRESENT_FILE" && exit 0
exit 22
EOF
chmod +x "$TMP_DIR/bin/curl"

export PATH="$TMP_DIR/bin:$PATH"
export PRESENT_FILE="$TMP_DIR/present.txt"
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

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all check-central-published tests passed"
