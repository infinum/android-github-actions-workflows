#!/usr/bin/env bash
#
# check-central-published.sh — is every artifact of this version already on
# Maven Central?
#
# Used to make the release pipeline converge: if a previous run published to
# Central but died before recording the GitHub release, the retry must skip
# the publish (Central coordinates are immutable) and go straight to
# recording.
#
# Note the propagation lag: publishAndReleaseToMavenCentral returns once the
# Portal releases the deployment, but repo1 can take 10-30 minutes to catch
# up. A retry inside that window will report false. Accepted: retries are
# driven by the next merge, which is far outside the window.
#
# Usage:
#   check-central-published.sh <group> <version> <artifact>...
#
# Output (one line):
#   published=true    every artifact is present
#   published=false   at least one is missing
#
set -euo pipefail

GROUP="${1:-}"
VERSION="${2:-}"
if [ -z "$GROUP" ] || [ -z "$VERSION" ]; then
  echo "usage: check-central-published.sh <group> <version> <artifact>..." >&2
  exit 2
fi
shift 2
if [ "$#" -eq 0 ]; then
  echo "at least one artifact id is required" >&2
  exit 2
fi

BASE_URL="${MAVEN_CENTRAL_BASE_URL:-https://repo1.maven.org/maven2}"
group_path="${GROUP//.//}"

for artifact in "$@"; do
  url="$BASE_URL/$group_path/$artifact/$VERSION/$artifact-$VERSION.pom"
  status="$(curl -sS -o /dev/null -w '%{http_code}' -I --max-time 30 "$url" || echo "000")"
  if [ "$status" != "200" ]; then
    echo "published=false"
    exit 0
  fi
done

echo "published=true"
