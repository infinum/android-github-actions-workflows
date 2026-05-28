#!/usr/bin/env python3
"""
Build a currency map of trusted top-level coords against the latest stable
release published on Google Maven, Gradle Plugin Portal, or Maven Central.

Output shape:
{
  "group:artifact:version": {"current": true|false, "latest": "x.y.z"}
}

Keys are the *exact* versioned coord strings that appear in the dep map's
`topLevels`, so categorize-alert.py can do a direct lookup with no
normalization.

Inputs:
  --dep-map         JSON produced by parse-gradle-deps.py
  --alerts          Cached `gh api dependabot/alerts` JSON
  --config          dismiss-config.json (trusted_sources, currency_threshold, ...)
  --output          Path to write the currency map JSON
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Optional


USER_AGENT = "infinum-dependabot-dismiss/1.0"
TIMEOUT_SECONDS = 10
RETRY_ATTEMPTS = 3       # attempts per repo URL before giving up on that repo
RETRY_BASE_DELAY = 0.5   # seconds; doubles each retry

MAVEN_REPOS = [
    "https://dl.google.com/dl/android/maven2",
    "https://plugins.gradle.org/m2",
    "https://repo1.maven.org/maven2",
]

PRERELEASE_MARKERS = ("-alpha", "-beta", "-rc", "-dev", "-snapshot")
VERSION_TAG = re.compile(r"<version>([^<]+)</version>")


def coord_of(versioned_id: str) -> str:
    parts = versioned_id.split(":")
    if len(parts) < 2:
        return versioned_id
    return f"{parts[0]}:{parts[1]}"


def matches_trusted_pattern(coord: str, patterns: list) -> bool:
    """`coord` is `group:artifact`. Patterns are either `group.with.dots.*`
    (matches the group exactly or any sub-group under it) or an exact
    `group:artifact`."""
    group = coord.split(":")[0]
    for p in patterns:
        if p.endswith(".*"):
            prefix = p[:-2]
            if group == prefix or group.startswith(prefix + "."):
                return True
        elif p == coord:
            return True
    return False


def version_sort_key(version: str) -> tuple:
    """Natural version ordering: split on dots, ints first then strings."""
    parts = []
    for chunk in version.split("."):
        try:
            parts.append((0, int(chunk)))
        except ValueError:
            parts.append((1, chunk))
    return tuple(parts)


def _fetch_url(url: str) -> Optional[str]:
    """Single-URL fetch with retry on transient errors. Returns the response
    body on 200, or None if a 4xx is encountered or all attempts fail. A 4xx
    short-circuits (genuine miss — no point retrying). 5xx and network-layer
    errors are retried with exponential backoff."""
    delay = RETRY_BASE_DELAY
    for attempt in range(RETRY_ATTEMPTS):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                if resp.status == 200:
                    return resp.read().decode("utf-8", errors="replace")
                return None
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                # Genuine "not at this URL" — try the next repo, no retry.
                return None
            # 5xx: transient server error, fall through to retry.
        except (urllib.error.URLError, TimeoutError, OSError):
            # Network/TLS/connection issues — retry.
            pass
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(delay)
            delay *= 2
    return None


def fetch_metadata(coord: str) -> Optional[str]:
    """Try each Maven repo in order; return first metadata XML body that loads.
    `coord` is `group:artifact`."""
    group, artifact = coord.split(":", 1)
    group_path = group.replace(".", "/")
    for base in MAVEN_REPOS:
        url = f"{base}/{group_path}/{artifact}/maven-metadata.xml"
        body = _fetch_url(url)
        if body is not None:
            return body
    return None


def latest_stable_from_metadata(xml: str) -> Optional[str]:
    versions = VERSION_TAG.findall(xml)
    stable = [
        v for v in versions
        if not any(marker in v.lower() for marker in PRERELEASE_MARKERS)
    ]
    if not stable:
        return None
    return sorted(stable, key=version_sort_key)[-1]


def is_current(project_version: str, latest: str, threshold: str) -> bool:
    if threshold == "latest":
        return project_version == latest
    if threshold == "same-minor":
        pv = ".".join(project_version.split(".")[:2])
        lv = ".".join(latest.split(".")[:2])
        return bool(pv) and pv == lv
    raise ValueError(f"unknown currency-threshold: {threshold!r}")


def collect_alert_packages(alerts: list) -> set:
    pkgs = set()
    for alert in alerts:
        pkg = alert.get("dependency", {}).get("package", {})
        if pkg.get("ecosystem") != "maven":
            continue
        name = pkg.get("name")
        if name:
            pkgs.add(name)
    return pkgs


def collect_relevant_top_levels(dep_map: dict, alert_pkgs: set) -> set:
    """Top-level versioned coords (across all configurations) that lead to a
    dep whose `group:artifact` matches one of the alert packages."""
    relevant = set()

    def scan_bucket(bucket: dict) -> None:
        for dep in bucket.get("allDeps", []):
            if coord_of(dep["id"]) in alert_pkgs:
                for tl in dep.get("topLevels", []):
                    relevant.add(tl)

    for proj in dep_map.get("projects", {}).values():
        for cfg in proj.get("configurations", {}).values():
            scan_bucket(cfg)
    for bs in dep_map.get("buildscriptClasspath", {}).values():
        scan_bucket(bs)

    return relevant


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dep-map", required=True)
    ap.add_argument("--alerts", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    with open(args.dep_map) as f:
        dep_map = json.load(f)
    with open(args.alerts) as f:
        alerts = json.load(f)
    with open(args.config) as f:
        config = json.load(f)

    trusted_sources = config["trusted_sources"]
    threshold = config["currency_threshold"]

    alert_pkgs = collect_alert_packages(alerts)
    relevant_top_levels = collect_relevant_top_levels(dep_map, alert_pkgs)

    candidates = sorted(
        tl for tl in relevant_top_levels
        if matches_trusted_pattern(coord_of(tl), trusted_sources)
    )

    currency: dict = {}
    metadata_cache: dict = {}  # group:artifact -> latest|None

    for tl in candidates:
        ga = coord_of(tl)
        version = tl.split(":", 2)[2] if tl.count(":") >= 2 else ""
        if ga not in metadata_cache:
            xml = fetch_metadata(ga)
            if xml is None:
                metadata_cache[ga] = None
            else:
                metadata_cache[ga] = latest_stable_from_metadata(xml)

        latest = metadata_cache[ga]
        if latest is None:
            # Demoted to ::notice:: — this is a conservative fallback rather
            # than something the user usually needs to act on. The categorizer
            # only consults currency when the trusted-source rule applies
            # (production/buildscript/codegen-main scopes), so test-config and
            # non-production occurrences are unaffected regardless.
            print(
                f"::notice::Maven currency lookup unavailable for {ga}; "
                f"treating as not current. Alerts whose dismissal would "
                f"require this trusted source to be current will be left open.",
                file=sys.stderr,
            )
            currency[tl] = {"current": False, "latest": "unknown"}
            continue

        currency[tl] = {
            "current": is_current(version, latest, threshold),
            "latest": latest,
        }

    with open(args.output, "w") as out:
        json.dump(currency, out, indent=2)

    print(
        f"Wrote currency map for {len(currency)} trusted top-level(s) "
        f"(scanned {len(relevant_top_levels)} alert-relevant top-level(s)).",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
