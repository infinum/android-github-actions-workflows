#!/usr/bin/env bash
#
# render-changelog.sh — given a GitHub Releases JSON array on stdin, write a
# Markdown changelog to stdout, newest release first.
#
# Replaces the committed CHANGELOG.md: the release flow no longer writes to
# the default branch, so release notes live in GitHub Releases and are
# rendered onto the documentation site at build time.
#
# Usage:
#   gh api repos/OWNER/NAME/releases --paginate --slurp \
#     | jq 'flatten(1)' | render-changelog.sh > docs/changelog.md
#
# Sorting: a plain `sort_by(date) | reverse` is unsafe here because jq's
# sort is stable — when releases share a sort key (notably: no date at all,
# which happens for draft-less fixtures and is exercised by the test suite)
# a stable ascending sort leaves ties in their original order, and the
# unconditional reverse then flips that original order instead of preserving
# it. The Releases API already returns releases newest-first, so ties must
# keep their original relative order. Pairing each release with its original
# index and sorting by [date, -index] before reversing achieves that: real
# date differences still dominate the ordering, and ties fall back to the
# original (already newest-first) position.
set -euo pipefail

releases="$(cat)"

echo "# Changelog"
echo ""

printf '%s' "$releases" | jq -r '
  [ .[] | select(.draft | not) ]
  | to_entries
  | sort_by([(.value.published_at // .value.created_at // ""), -.key])
  | reverse
  | .[].value
  | "## \(.tag_name)\n\n\(.body // "_No release notes._")\n"
'
