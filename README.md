# android-github-actions-workflows

## Dismiss dev-only Dependabot alerts

[`dismiss-dev-only-dependabot-alerts.yml`](.github/workflows/dismiss-dev-only-dependabot-alerts.yml)
is a reusable workflow that closes Dependabot alerts whose every reachable
occurrence sits in a configuration that never ships to production — test
source sets, non-production variants, build tooling (lint, Detekt, Jacoco,
Dokka, …), or current transitives of trusted Maven groups. Alerts with any
production-reachable occurrence stay open for human review.

### How it works

1. **`list-alerts`** mints a GitHub App installation token (the default
   `GITHUB_TOKEN` can't reach the Dependabot Alerts API) and fetches all open
   alerts. If there are none, the `dismiss` job is skipped.
2. **`dismiss`** checks out the caller repo and the tooling scripts, sets up
   JDK + Android SDK + Python, then runs the analysis pipeline:
   - [`gather-deps.sh`](scripts/gather-deps.sh) — per-module Gradle dependency
     output (composite-build aware).
   - [`parse-gradle-deps.py`](scripts/parse-gradle-deps.py) — turns that text
     into a dependency→configuration map, computing reachability from the root
     build's modules.
   - [`build-trusted-currency.py`](scripts/build-trusted-currency.py) — checks
     each trusted top-level against the latest release on Google Maven, the
     Gradle Plugin Portal, or Maven Central.
   - [`categorize-alert.py`](scripts/categorize-alert.py) — decides
     `dismiss` or `skip` per alert.
   - [`format-dismissal-comment.py`](scripts/format-dismissal-comment.py) —
     builds the ≤280-char dismissal comment with a link back to the run.

Every run writes its configuration and a per-alert decision table to the job
summary. When `dry-run` is `true` (the default) decisions are logged but no
alerts are dismissed.

### Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `client-id` | yes | — | App ID (or Client ID) of the `infinum-dependabot-dismisser` GitHub App. |
| `dry-run` | no | `true` | When `true`, log decisions without dismissing. |
| `java-version` | no | `17` | JDK for the Gradle run; use `11` for AGP 7.x or older. |
| `trusted-sources` | no | `""` | Extra Maven-group glob patterns (one per line) appended to the built-in defaults (`com.android.*`, `androidx.*`, `org.jetbrains.kotlin.*`, `org.jetbrains.*`, `com.google.*`). |
| `trusted-source-scopes` | no | `buildscript` | Scopes (one per line) where the trusted-source rule applies. Allowed: `buildscript`, `production`, `codegen-main`. |
| `production-build-types` | no | `release` | Build type names (lowercase, one per line) considered production-shipping. |
| `production-variants` | no | `""` | Exact variant names (one per line); when non-empty, overrides `production-build-types`. |
| `currency-threshold` | no | `latest` | How current a trusted top-level must be: `latest` (exact) or `same-minor` (any patch in the latest `major.minor`). |

### Secrets

| Secret | Required | Description |
| --- | --- | --- |
| `app-private-key` | yes | PEM private key of the `infinum-dependabot-dismisser` GitHub App, used to mint a token with `Dependabot alerts: read/write` on the caller repo. |

### Usage

```yaml
name: Dismiss dev-only Dependabot alerts

on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

jobs:
  dismiss:
    uses: infinum/android-github-actions-workflows/.github/workflows/dismiss-dev-only-dependabot-alerts.yml@main
    with:
      client-id: ${{ vars.DEPENDABOT_DISMISSER_BOT_APP_ID }}
      dry-run: false
    secrets:
      app-private-key: ${{ secrets.DEPENDABOT_DISMISSER_BOT_PRIVATE_KEY }}
```

