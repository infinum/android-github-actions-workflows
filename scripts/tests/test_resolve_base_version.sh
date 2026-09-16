#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/resolve-base-version.sh"
FAILURES=0

assert_output() {
  local name="$1" input="$2" expected_tag="$3" expected_version="$4"
  local output tag version
  output="$(printf '%s' "$input" | bash "$SCRIPT")"
  tag="$(printf '%s\n' "$output" | grep '^base_tag=' | cut -d= -f2-)"
  version="$(printf '%s\n' "$output" | grep '^base_version=' | cut -d= -f2-)"
  if [ "$tag" = "$expected_tag" ] && [ "$version" = "$expected_version" ]; then
    echo "ok   - $name"
  else
    echo "FAIL - $name"
    echo "       expected base_tag=$expected_tag base_version=$expected_version"
    echo "       got      base_tag=$tag base_version=$version"
    FAILURES=$((FAILURES + 1))
  fi
}

rel() { printf '{"tag_name":"%s","draft":%s,"prerelease":%s}' "$1" "$2" "$3"; }

assert_output "double-digit majors sort numerically" \
  "[$(rel v2.2.3 false false),$(rel v12.1.3 false false),$(rel v10.0.0 false false)]" \
  "v12.1.3" "12.1.3"

assert_output "double-digit minors sort numerically" \
  "[$(rel v0.9.0 false false),$(rel v0.10.0 false false),$(rel v0.2.0 false false)]" \
  "v0.10.0" "0.10.0"

assert_output "patch versions are ordered correctly" \
  "[$(rel v0.7.0 false false),$(rel v0.7.3 false false),$(rel v0.7.2 false false),$(rel v0.1.2 false false)]" \
  "v0.7.3" "0.7.3"

assert_output "drafts are ignored" \
  "[$(rel v0.2.0 false false),$(rel v9.9.9 true false)]" \
  "v0.2.0" "0.2.0"

assert_output "prereleases are ignored" \
  "[$(rel v0.2.0 false false),$(rel v9.9.9 false true)]" \
  "v0.2.0" "0.2.0"

assert_output "no releases yields the 0.0.0 bootstrap" \
  "[]" \
  "" "0.0.0"

assert_output "only drafts yields the 0.0.0 bootstrap" \
  "[$(rel v1.0.0 true false)]" \
  "" "0.0.0"

assert_output "non-semver tag names are ignored" \
  "[$(rel v0.2.0 false false),$(rel nightly false false),$(rel v1.2 false false)]" \
  "v0.2.0" "0.2.0"

assert_output "tags without a v prefix are accepted" \
  "[$(rel 0.3.0 false false),$(rel 0.2.0 false false)]" \
  "0.3.0" "0.3.0"

assert_output "mixed prefixes: bare tag is highest" \
  "[$(rel 9.0.0 false false),$(rel v1.0.0 false false)]" \
  "9.0.0" "9.0.0"

assert_output "mixed prefixes: v-prefixed tag is highest" \
  "[$(rel 2.5.0 false false),$(rel v9.0.0 false false)]" \
  "v9.0.0" "9.0.0"

assert_output "mixed prefixes spanning double digits" \
  "[$(rel v2.2.3 false false),$(rel 10.0.0 false false),$(rel v12.1.3 false false)]" \
  "v12.1.3" "12.1.3"

assert_output "base_tag preserves the original prefix exactly" \
  "[$(rel v5.0.0 false false),$(rel 0.9.0 false false)]" \
  "v5.0.0" "5.0.0"

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all resolve-base-version tests passed"
