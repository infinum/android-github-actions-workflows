#!/usr/bin/env python3
"""
Compose a dismissal-comment string that fits the GitHub Dependabot Alerts
API's 280-character cap.

The categorizer emits plain text (no markdown). This helper joins reason +
detail, appends a link back to the workflow run for the audit trail, and
truncates the body if needed.

Args (positional, all required):
  reason   the per-alert primary reason from categorize-alert.py (plain text)
  detail   the per-alert detail line, may be empty (plain text)
  run-url  URL to this workflow run

Writes the final comment to stdout. Always ≤ 280 unicode characters.
"""
import sys


MAX_CHARS = 280


def compose(reason: str, detail: str, run_url: str) -> str:
    reason = reason.strip()
    detail = detail.strip()
    body = reason if not detail else f"{reason} [{detail}]"
    suffix = f" (see {run_url})" if run_url else ""

    full = body + suffix
    if len(full) <= MAX_CHARS:
        return full

    # Truncate the body; keep the run URL intact so the audit trail is never
    # lost. Reserve one character for the ellipsis.
    budget = MAX_CHARS - len(suffix) - 1
    if budget < 1:
        # Pathologically long URL — fall back to truncating the whole thing.
        return full[: MAX_CHARS - 1] + "…"
    return body[:budget].rstrip() + "…" + suffix


def main() -> None:
    if len(sys.argv) != 4:
        print(
            "usage: format-dismissal-comment.py <reason> <detail> <run-url>",
            file=sys.stderr,
        )
        sys.exit(2)
    reason, detail, run_url = sys.argv[1], sys.argv[2], sys.argv[3]
    print(compose(reason, detail, run_url), end="")


if __name__ == "__main__":
    main()
