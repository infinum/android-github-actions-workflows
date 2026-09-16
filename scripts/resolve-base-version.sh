#!/usr/bin/env bash
#
# resolve-base-version.sh — given a GitHub Releases JSON array on stdin, print
# the highest released version.
#
# Drafts and prereleases are excluded, and tag names that are not plain
# semver are ignored. Ordering uses `sort -V`, which compares digit runs
# numerically — plain `sort` puts v12.1.3 before v2.2.3.
#
# Deliberately NOT /releases/latest: that endpoint returns the most recently
# published release by date, so a patch on an older line would regress the
# next computed version.
#
# Usage:
#   gh api repos/OWNER/NAME/releases --paginate | resolve-base-version.sh
#
# Output (always two lines):
#   base_tag=v0.7.3       empty when there is no released version
#   base_version=0.7.3    0.0.0 when there is no released version
#
set -euo pipefail

releases="$(cat)"

tags="$(printf '%s' "$releases" \
  | jq -r '.[] | select(.draft | not) | select(.prerelease | not) | .tag_name' \
  | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' || true)"

if [ -z "$tags" ]; then
  echo "base_tag="
  echo "base_version=0.0.0"
  exit 0
fi

base_tag="$(printf '%s\n' "$tags" | sort -V | tail -1)"

echo "base_tag=$base_tag"
echo "base_version=${base_tag#v}"
