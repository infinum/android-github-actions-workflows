# android-github-actions-workflows

## Dismiss dev-only Dependabot alerts

[`dismiss-dev-only-dependabot-alerts.yml`](.github/workflows/dismiss-dev-only-dependabot-alerts.yml)
is a reusable workflow that closes Dependabot alerts whose every reachable
occurrence sits in a configuration that never ships to production — test
source sets, non-production variants, build tooling (lint, Detekt, Jacoco,
Dokka, …), or current transitives of trusted Maven groups. Alerts with any
production-reachable occurrence stay open for human review.

### Architecture

The analysis pipeline is packaged as a **composite action**
([`.github/actions/dismiss-dev-only-dependabot-alerts`](.github/actions/dismiss-dev-only-dependabot-alerts/action.yml)) —
the single source of truth. Two entry points wrap it:

- **Reusable workflow** (the workflow linked above) — for the common case that needs no
  custom setup. It gates on the open-alert count, checks out the caller repo,
  then delegates to the composite action.
- **Composite action, called directly** — for projects that must run their
  own pre-steps between checkout and the analysis (install a CLI, fetch
  secrets from Vault or any backend). See
  [Calling the action directly](#calling-the-action-directly).

See [When to use which](#when-to-use-which) to choose.

### How it works

1. **`list-alerts`** mints a GitHub App installation token (the default
   `GITHUB_TOKEN` can't reach the Dependabot Alerts API) and fetches all open
   alerts. If there are none, the `dismiss` job is skipped.
2. **`dismiss`** checks out the caller repo (submodules included — they are
   other infinum private repos) and runs the composite action, which
   materializes the Gradle wrapper jar from LFS, sets up JDK + Android SDK +
   Python, then runs the analysis pipeline. The action re-fetches the open
   alerts and self-gates on them, so it also skips the heavy work when nothing
   is open. The pipeline scripts:
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

### Usage (reusable workflow)

For the common case — a project that needs no setup beyond checkout:

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

### Calling the action directly

Use the composite action directly when the project needs project-specific
setup **after checkout but before Gradle configures** — for example fetching a
private Maven repository URL from Vault. A reusable workflow cannot accept
caller-provided `uses:` steps, so these projects own their checkout and setup
and then hand off to the action.

The action does **not** check out the repo or source any secrets; the caller
job does both. Everything after checkout (including the LFS wrapper fix) runs
inside the action against the already-checked-out workspace, so any setup you
run before it — like the Vault fetch below — is in place when Gradle
configures.

Composite actions have no `secrets:` block, so the private key is passed as the
`app-private-key` input. GitHub still masks it when it comes from a secret.

```yaml
name: Dismiss dev-only Dependabot alerts

on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

jobs:
  dismiss:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/create-github-app-token@v3
        id: token
        with:
          client-id: ${{ vars.DEPENDABOT_DISMISSER_BOT_APP_ID }}
          private-key: ${{ secrets.DEPENDABOT_DISMISSER_APP_PRIVATE_KEY }}
          owner: ${{ github.repository_owner }}
      - uses: actions/checkout@v6
        with:
          token: ${{ steps.token.outputs.token }}   # needed for private submodules
          submodules: recursive
      # --- project-specific setup goes here ---
      - uses: eLco/setup-vault@1a8cc6f3c818a0e71b6fade4a922eeec95069edf
      - name: Fetch secrets from Vault
        env:
          VAULT_ADDR: ${{ vars.VAULT_ADDR }}
          VAULT_AUTH_TOKEN: ${{ secrets.VAULT_AUTH_TOKEN }}
        run: |
          chmod +x ./vault-fetch.sh
          ./vault-fetch.sh
      # --- hand off to the shared engine ---
      - uses: infinum/android-github-actions-workflows/.github/actions/dismiss-dev-only-dependabot-alerts@main
        with:
          client-id: ${{ vars.DEPENDABOT_DISMISSER_BOT_APP_ID }}
          app-private-key: ${{ secrets.DEPENDABOT_DISMISSER_APP_PRIVATE_KEY }}
          dry-run: "false"
```

The action accepts the same tuning inputs as the reusable workflow
([Inputs](#inputs) above), plus `app-private-key`.

### When to use which

| | Reusable workflow | Composite action (direct) |
| --- | --- | --- |
| Setup needed | None beyond checkout | Custom pre-steps (install tools, fetch secrets) |
| Who checks out the repo | The workflow | Your job |
| Secret handling | `secrets: app-private-key` | `with: app-private-key` (from a secret) |
| Boilerplate | Minimal — one `uses:` | You write the checkout + setup steps |

Prefer the reusable workflow. Reach for the action only when the workflow's
fixed checkout-then-analyze sequence leaves no room for a step you must run in
between.

