# Tag-Derived Versioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the push-to-main release flow for the Infinum Android common modules with tag-derived versioning, so that no release step ever writes to a protected branch and no tag or release is created until the Maven Central publish has actually succeeded.

**Architecture:** The next version is computed from the highest non-draft, non-prerelease GitHub Release rather than from `version.properties`. CI injects it into Gradle as `-PreleaseVersion`. The publish runs first; only if it succeeds does a single `createRelease` API call create the tag and the release together. Logic that can be tested offline lives in `scripts/` as plain bash and is invoked by composite actions through the repo's existing `$GITHUB_ACTION_PATH/../../../scripts` pattern.

**Tech Stack:** GitHub Actions (composite + Node 24 JavaScript actions), bash, jq, Gradle 9.x with Kotlin DSL, `com.vanniktech.maven.publish` 0.37.0 (pilot) / 0.32.0 (rehearsal), GitHub REST + GraphQL API via `@actions/github`.

**Spec:** `docs/superpowers/specs/2026-09-15-tag-derived-versioning-design.md`

**On the spec's Phase 0 (baseline):** the read-only snapshot — tags, releases, Central
versions and CI state for all seven repos — is already recorded in the spec document and
needs no task. The one part that cannot be read from outside, confirming the Maven Central
credentials are Portal tokens rather than OSSRH ones, is Task 14 Step 1.

## Global Constraints

- The deploy step must complete successfully before any tag or release is created. A failed deploy must leave no tag, no release, and no partially recorded state.
- Maven Central is the source of truth for what shipped; the GitHub Release is a derived record that retries until it catches up. Never record before publishing.
- Portal deployments are **never** dropped automatically. `dropMavenCentralDeployment` is a human decision only.
- Real Maven Central is **never** touched from `infinum/android-common-projects-test-setup`. Its deploy step stays `publishToMavenLocal` throughout.
- `version.properties` and `CHANGELOG.md` are **not deleted** by this plan. They are deleted in a separate PR after the tech lead reviews the migration.
- Every action in this repo is referenced as `@main`. Any edit to an existing shared action goes live for all seven consumer repos on their next run. Only pure fixes may modify existing actions; new behaviour goes into new actions.
- Do not use `/releases/latest` anywhere. It orders by publication date, not semver.
- Deprecated actions stay in the repo until all seven repos are migrated: `read_current_version`, `find_current_tag`, `write_updated_version`, `update_changelog`, `push_version_update`, `push_version_tag`, `common_modules_postdeploy`, `common_modules_predeploy_properties`.
- Composite actions locate repo scripts with the existing pattern, exactly as `.github/actions/dismiss-dev-only-dependabot-alerts/action.yml:113` does:
  `echo "SCRIPTS_DIR=$(cd "$GITHUB_ACTION_PATH/../../../scripts" && pwd)" >> "$GITHUB_ENV"`
- Bash scripts and tests start with `#!/usr/bin/env bash` and `set -euo pipefail`. Tests use `mktemp -d` with a `trap cleanup EXIT`, and stub external binaries by prepending a temp dir to `PATH`, matching `scripts/tests/test_gather_deps.sh`.
- `gh` is shadowed by a shell function on the maintainer's machine. In any local command, call the CLI as `command gh`. Inside Actions runners plain `gh` is correct.

## File Structure

**`infinum/android-github-actions-workflows`**

| Path | Responsibility |
|---|---|
| `scripts/resolve-base-version.sh` | Pure: Releases JSON on stdin → highest released tag + version. No network. |
| `scripts/check-central-published.sh` | Pure-ish: given coordinates, probe Maven Central per artifact. Network via `curl`, stubbable. |
| `scripts/tests/test_resolve_base_version.sh` | Offline tests for the above, incl. semver ordering. |
| `scripts/tests/test_check_central_published.sh` | Offline tests with a stubbed `curl`. |
| `.github/actions/get_pull_request_details/pr-data.js` | Pure: shape one PR API response into changelog data; derive bump flags. |
| `.github/actions/get_pull_request_details/test/pr-data.test.js` | `node --test` unit tests for the above. |
| `.github/actions/get_pull_request_details/index.js` | Thin wrapper: API calls + `core` I/O only. |
| `.github/actions/create_github_release/release-errors.js` | Pure: recognise a "release already exists" 422. |
| `.github/actions/create_github_release/test/release-errors.test.js` | `node --test` unit tests for the above. |
| `.github/actions/create_github_release/index.js` | Creates tag + release in one call; idempotent. |
| `.github/actions/resolve_base_version/action.yml` | Composite wrapper around `resolve-base-version.sh`. |
| `.github/actions/check_central_published/action.yml` | Composite wrapper around `check-central-published.sh`. |
| `.github/actions/common_modules_predeploy_release/action.yml` | Composite: resolve → commits → PRs → bump → changelog. Writes no files. |
| `.github/workflows/test-scripts.yml` | Runs bash, Python and `node --test` suites. |

**`infinum/android-common-projects-test-setup`** (rehearsal) and **`infinum/android-common-kotlin`** (pilot)

| Path | Responsibility |
|---|---|
| `build.gradle.kts` | Version from `-PreleaseVersion`; hard fail for publish tasks. |
| `.github/workflows/release.yml` | New release pipeline. Dispatch-only until cutover. |
| `.github/workflows/static.yml` | *(pilot only)* Renders `docs/changelog.html` from the Releases API. |

---

### Task 1: Extract and fix PR data shaping

Removes the `body` field that blows `ARG_MAX`, and moves the shaping logic into a pure, testable module.

**Files:**
- Create: `.github/actions/get_pull_request_details/pr-data.js`
- Create: `.github/actions/get_pull_request_details/test/pr-data.test.js`
- Modify: `.github/actions/get_pull_request_details/index.js`
- Modify: `.github/workflows/test-scripts.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `toPrData(prDetail) -> { title: string, labels: string[], number: number, author: string }` and `deriveBumpFlags(prDataList) -> { breakingChange: boolean, newFeature: boolean, bugfix: boolean }` and `hasSkipRelease(labels) -> boolean`, all exported from `pr-data.js`. Task 8 relies on the action's existing output names being unchanged: `pr_details`, `is_breaking_change`, `is_new_feature`, `is_bugfix`.

- [ ] **Step 1: Write the failing test**

Create `.github/actions/get_pull_request_details/test/pr-data.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert');
const { toPrData, deriveBumpFlags, hasSkipRelease } = require('../pr-data');

const prFixture = {
  title: 'Update Gradle to v9.7.1',
  body: 'x'.repeat(200000),
  number: 40,
  user: { login: 'renovate' },
  labels: [{ name: 'bugfix' }]
};

test('toPrData drops the PR body', () => {
  const result = toPrData(prFixture);
  assert.strictEqual(result.body, undefined);
  assert.deepStrictEqual(Object.keys(result).sort(), ['author', 'labels', 'number', 'title']);
});

test('toPrData keeps the fields the changelog uses', () => {
  assert.deepStrictEqual(toPrData(prFixture), {
    title: 'Update Gradle to v9.7.1',
    labels: ['bugfix'],
    number: 40,
    author: 'renovate'
  });
});

test('toPrData output stays small for a huge PR body', () => {
  assert.ok(JSON.stringify(toPrData(prFixture)).length < 200);
});

test('deriveBumpFlags reports each label independently', () => {
  const prs = [
    { labels: ['bugfix'] },
    { labels: ['new-feature'] },
    { labels: [] }
  ];
  assert.deepStrictEqual(deriveBumpFlags(prs), {
    breakingChange: false,
    newFeature: true,
    bugfix: true
  });
});

test('deriveBumpFlags detects breaking changes', () => {
  assert.strictEqual(deriveBumpFlags([{ labels: ['breaking-change'] }]).breakingChange, true);
});

test('deriveBumpFlags on an empty list is all false', () => {
  assert.deepStrictEqual(deriveBumpFlags([]), {
    breakingChange: false,
    newFeature: false,
    bugfix: false
  });
});

test('hasSkipRelease detects the skip-release label', () => {
  assert.strictEqual(hasSkipRelease(['skip-release']), true);
  assert.strictEqual(hasSkipRelease(['bugfix']), false);
  assert.strictEqual(hasSkipRelease([]), false);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test .github/actions/get_pull_request_details/test/*.test.js`
Expected: FAIL — `Cannot find module '../pr-data'`

- [ ] **Step 3: Write the minimal implementation**

Create `.github/actions/get_pull_request_details/pr-data.js`:

```javascript
// Pure helpers for shaping pull request API responses into changelog data.
//
// The PR body is deliberately NOT carried. generate_changelog reads only
// title, author, number and labels, and passing bodies between steps
// overflows ARG_MAX once a release backlog builds up.

const BREAKING_CHANGE = 'breaking-change';
const NEW_FEATURE = 'new-feature';
const BUGFIX = 'bugfix';
const SKIP_RELEASE = 'skip-release';

function toPrData(prDetail) {
  return {
    title: prDetail.title,
    labels: prDetail.labels.map(label => label.name),
    number: prDetail.number,
    author: prDetail.user.login
  };
}

function deriveBumpFlags(prDataList) {
  const has = label => prDataList.some(pr => pr.labels.includes(label));
  return {
    breakingChange: has(BREAKING_CHANGE),
    newFeature: has(NEW_FEATURE),
    bugfix: has(BUGFIX)
  };
}

function hasSkipRelease(labels) {
  return labels.includes(SKIP_RELEASE);
}

module.exports = { toPrData, deriveBumpFlags, hasSkipRelease };
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test .github/actions/get_pull_request_details/test/*.test.js`
Expected: PASS — 7 tests

- [ ] **Step 5: Rewrite index.js to use the module**

Replace `.github/actions/get_pull_request_details/index.js` entirely:

```javascript
const core = require('@actions/core');
const github = require('@actions/github');
const { context } = require('@actions/github');
const { toPrData, deriveBumpFlags, hasSkipRelease } = require('./pr-data');

async function run() {
  try {
    const prNumbers = core.getInput('pr_numbers');
    if (!prNumbers) {
      core.info('No pull request numbers provided.');
      return;
    }

    const token = core.getInput('github_token');
    const octokit = github.getOctokit(token);
    const prNumberList = prNumbers.split(' ').filter(Boolean);

    const mostRecentPr = prNumberList[prNumberList.length - 1];
    const { data: mostRecentPrDetail } = await octokit.rest.pulls.get({
      owner: context.repo.owner,
      repo: context.repo.repo,
      pull_number: mostRecentPr
    });

    if (hasSkipRelease(mostRecentPrDetail.labels.map(label => label.name))) {
      core.info('Most recent PR has skip-release label. Skipping the release.');
      core.exportVariable('pr_details', '[]');
      core.setOutput('pr_details', '[]');
      return;
    }

    const prDetails = [];
    for (const pr of prNumberList) {
      const { data: prDetail } = await octokit.rest.pulls.get({
        owner: context.repo.owner,
        repo: context.repo.repo,
        pull_number: pr
      });
      prDetails.push(toPrData(prDetail));
    }

    const { breakingChange, newFeature, bugfix } = deriveBumpFlags(prDetails);
    const serialized = JSON.stringify(prDetails);

    core.exportVariable('pr_details', serialized);
    core.exportVariable('breaking_change', breakingChange);
    core.exportVariable('new_feature', newFeature);
    core.exportVariable('bugfix', bugfix);

    core.setOutput('pr_details', serialized);
    core.setOutput('is_breaking_change', breakingChange);
    core.setOutput('is_new_feature', newFeature);
    core.setOutput('is_bugfix', bugfix);

    core.info(`pr_details bytes=${serialized.length} count=${prDetails.length}`);
    core.info(`breaking_change=${breakingChange}`);
    core.info(`new_feature=${newFeature}`);
    core.info(`bugfix=${bugfix}`);
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
```

- [ ] **Step 6: Wire node tests into CI**

In `.github/workflows/test-scripts.yml`, append these steps after the existing
`Run gather-deps.sh test` step. Leave the `on:` block exactly as it is — this workflow
has no `paths:` filters on `main` and runs on every push and pull request; adding one
now would be an unrelated behaviour change that could regress triggering for the
existing Python and bash suites:

```yaml
      - name: Set up Node
        uses: actions/setup-node@v6
        with:
          node-version: '24'

      - name: Run JavaScript action unit tests
        run: node --test .github/actions/*/test/*.test.js
```

- [ ] **Step 7: Run the full suite**

Run: `node --test .github/actions/*/test/*.test.js`
Expected: PASS

Use the glob form, not `node --test <directory>` — the directory form crashes with
`Cannot find module` on the Node versions in use here.

- [ ] **Step 8: Commit**

```bash
git add .github/actions/get_pull_request_details .github/workflows/test-scripts.yml
git commit -m "fix: stop carrying PR bodies between release steps

generate_changelog reads only title, author, number and labels, but
get_pull_request_details also carried the full PR body. With a release
backlog of 26 PRs, including dumped Copilot prompt blocks, that overflows
ARG_MAX and the workflow dies before it reaches the publish step.

Extracts the shaping into a pure module so it can be unit tested, and
wires node --test into the existing test workflow."
```

---

### Task 2: Move JavaScript actions to Node 24

`node20` is deprecated and every run prints a warning.

**Files:**
- Modify: `.github/actions/create_github_release/action.yml:15`
- Modify: `.github/actions/find_pull_requests/action.yml:14`
- Modify: `.github/actions/get_pull_request_details/action.yml:20`
- Modify: `.github/actions/generate_changelog/action.yml:24`
- Modify: `.github/actions/update_changelog/action.yml:16`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Runtime change only.

- [ ] **Step 1: Confirm the current state**

Run: `grep -rn "using: 'node20'" .github/actions/*/action.yml`
Expected: 5 matches, one per file listed above.

- [ ] **Step 2: Apply the change**

```bash
sed -i '' "s/using: 'node20'/using: 'node24'/" \
  .github/actions/create_github_release/action.yml \
  .github/actions/find_pull_requests/action.yml \
  .github/actions/get_pull_request_details/action.yml \
  .github/actions/generate_changelog/action.yml \
  .github/actions/update_changelog/action.yml
```

(On a Linux runner drop the `''` after `-i`.)

- [ ] **Step 3: Verify**

Run: `grep -rn "using: 'node" .github/actions/*/action.yml`
Expected: 5 matches, all `node24`, no `node20` remaining.

- [ ] **Step 4: Verify the unit tests still pass on the new runtime**

Run: `node --test .github/actions/*/test/*.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .github/actions/*/action.yml
git commit -m "chore: move JavaScript actions to node24

The runner warns that node20 is deprecated on every step."
```

---

### Task 3: Make release creation atomic and idempotent

`createRelease` creates the tag from `target_commitish` when the tag does not exist, so tag and release become one server-side operation and `push_version_tag` is no longer needed. Tolerating a duplicate makes the "deploy succeeded, record failed" retry converge.

**Files:**
- Create: `.github/actions/create_github_release/release-errors.js`
- Create: `.github/actions/create_github_release/test/release-errors.test.js`
- Modify: `.github/actions/create_github_release/index.js`
- Modify: `.github/actions/create_github_release/action.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `isAlreadyExistsError(error) -> boolean` from `release-errors.js`. The action gains an optional input `target_commitish` (defaults to `$GITHUB_SHA`) and an output `release_url`.

- [ ] **Step 1: Write the failing test**

Create `.github/actions/create_github_release/test/release-errors.test.js`:

```javascript
const test = require('node:test');
const assert = require('node:assert');
const { isAlreadyExistsError } = require('../release-errors');

test('recognises the GitHub duplicate-release 422', () => {
  const error = {
    status: 422,
    response: {
      data: {
        message: 'Validation Failed',
        errors: [{ resource: 'Release', code: 'already_exists', field: 'tag_name' }]
      }
    }
  };
  assert.strictEqual(isAlreadyExistsError(error), true);
});

test('a 422 for another reason is not a duplicate', () => {
  const error = {
    status: 422,
    response: {
      data: {
        message: 'Validation Failed',
        errors: [{ resource: 'Release', code: 'invalid', field: 'tag_name' }]
      }
    }
  };
  assert.strictEqual(isAlreadyExistsError(error), false);
});

test('non-422 statuses are never duplicates', () => {
  assert.strictEqual(isAlreadyExistsError({ status: 500, response: { data: {} } }), false);
  assert.strictEqual(isAlreadyExistsError({ status: 404, response: { data: {} } }), false);
});

test('malformed errors do not throw', () => {
  assert.strictEqual(isAlreadyExistsError({}), false);
  assert.strictEqual(isAlreadyExistsError({ status: 422 }), false);
  assert.strictEqual(isAlreadyExistsError(new Error('boom')), false);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test .github/actions/create_github_release/test/*.test.js`
Expected: FAIL — `Cannot find module '../release-errors'`

- [ ] **Step 3: Write the minimal implementation**

Create `.github/actions/create_github_release/release-errors.js`:

```javascript
// Recognises the 422 GitHub returns when a release for the tag already exists.
//
// This is the "deploy succeeded, record failed" retry path: the previous run
// published to Maven Central and created the release, then died before
// reporting success. Re-running must converge rather than fail.

function isAlreadyExistsError(error) {
  if (!error || error.status !== 422) {
    return false;
  }
  const errors = error.response && error.response.data && error.response.data.errors;
  if (!Array.isArray(errors)) {
    return false;
  }
  return errors.some(entry => entry && entry.code === 'already_exists');
}

module.exports = { isAlreadyExistsError };
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test .github/actions/create_github_release/test/*.test.js`
Expected: PASS — 4 tests

- [ ] **Step 5: Rewrite index.js**

Replace `.github/actions/create_github_release/index.js` entirely:

```javascript
const core = require('@actions/core');
const github = require('@actions/github');
const { context } = require('@actions/github');
const { isAlreadyExistsError } = require('./release-errors');

async function run() {
  try {
    const newVersion = core.getInput('updated_version');
    const ghToken = core.getInput('github_token');
    const changelog = core.getInput('changelog');
    const targetCommitish = core.getInput('target_commitish') || process.env.GITHUB_SHA;

    if (!targetCommitish) {
      core.setFailed('No target_commitish supplied and GITHUB_SHA is unset.');
      return;
    }

    const octokit = github.getOctokit(ghToken);
    const tag = `v${newVersion}`;

    try {
      const releaseResponse = await octokit.rest.repos.createRelease({
        owner: context.repo.owner,
        repo: context.repo.repo,
        tag_name: tag,
        target_commitish: targetCommitish,
        name: tag,
        body: changelog
      });
      core.info(`Created tag ${tag} at ${targetCommitish} and release ${releaseResponse.data.html_url}`);
      core.setOutput('release_url', releaseResponse.data.html_url);
    } catch (error) {
      if (isAlreadyExistsError(error)) {
        core.info(`Release ${tag} already exists; treating as success.`);
        core.setOutput('release_url', '');
        return;
      }
      throw error;
    }
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
```

- [ ] **Step 6: Add the input and output to action.yml**

Replace `.github/actions/create_github_release/action.yml` entirely:

```yaml
name: 'Create GitHub release'
description: 'Creates the tag and the GitHub release in a single API call'
inputs:
  updated_version:
    description: 'The updated version'
    required: true
  changelog:
    description: 'The changelog to include in the release'
    required: true
  github_token:
    description: 'The GitHub token'
    required: true
  target_commitish:
    description: 'Commit the tag is created from. Defaults to GITHUB_SHA.'
    required: false
    default: ''

outputs:
  release_url:
    description: 'URL of the created release, empty when it already existed'

runs:
  using: 'node24'
  main: 'index.js'
```

- [ ] **Step 7: Run the full suite**

Run: `node --test .github/actions/*/test/*.test.js`
Expected: PASS

Use the glob form, not `node --test <directory>` — the directory form crashes with
`Cannot find module` on the Node versions in use here.

- [ ] **Step 8: Commit**

```bash
git add .github/actions/create_github_release
git commit -m "feat: create the tag and release in one API call

createRelease creates the tag from target_commitish when it does not
exist, so tag and release become a single server-side operation and
push_version_tag is no longer needed. A duplicate 422 is now treated as
success, so a run that published to Central but died before recording
converges on retry instead of failing forever."
```

---

### Task 4: Decouple commits_since_tag from its sibling action

It currently reads `env.tag`, set by `find_current_tag`, instead of its own input. The new flow has no `find_current_tag`, and a repo with no releases has no tag at all.

**Files:**
- Modify: `.github/actions/commits_since_tag/action.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: unchanged output `commits` — a space-separated list of commit SHAs. Now accepts an empty `tag` input, in which case it returns the full history.

- [ ] **Step 1: Replace the action**

Replace `.github/actions/commits_since_tag/action.yml` entirely:

```yaml
name: 'Find commits from tag until the HEAD'
description: 'Finds the commits from the given tag until HEAD. With no tag, returns the full history.'

inputs:
  tag:
    description: 'The tag to find the commits from. Empty means "no release yet".'
    required: false
    default: ''

outputs:
  commits:
    description: 'The commits from the tag until HEAD, separated by spaces'
    value: ${{ steps.find_commits.outputs.commits }}

runs:
  using: 'composite'
  steps:
    - name: Find commits from tag until the HEAD
      id: find_commits
      shell: bash
      env:
        FIND_COMMITS_TAG: ${{ inputs.tag }}
      run: |
        set -euo pipefail
        if [ -z "$FIND_COMMITS_TAG" ]; then
          echo "No tag supplied; taking the full history."
          commits=$(git log HEAD --pretty=format:"%H" | tr '\n' ' ')
        else
          git fetch origin tag "$FIND_COMMITS_TAG" --no-tags
          commits=$(git log "$FIND_COMMITS_TAG"..HEAD --pretty=format:"%H" | tr '\n' ' ')
        fi
        echo "commits=$commits" >> "$GITHUB_ENV"
        echo "commits=$commits" >> "$GITHUB_OUTPUT"
        echo "commits=$commits"
```

- [ ] **Step 2: Verify the sibling coupling is gone**

Run: `grep -n "env.tag" .github/actions/commits_since_tag/action.yml`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add .github/actions/commits_since_tag/action.yml
git commit -m "fix: read the tag from the input, not a sibling action's env

commits_since_tag read env.tag, which find_current_tag happened to set.
The new release flow has no find_current_tag, and a repo with no
releases has no tag at all — that case now returns the full history."
```

---

### Task 5: GATE — verify the Phase 1 canary

No code. This proves Tasks 1–4 work across consumer repos before anything new is built on them. **Do not proceed past this gate if the expected failure does not move.**

**Files:** none.

**Interfaces:**
- Consumes: Tasks 1–4, merged to `main` in this repo.
- Produces: confidence that `ARG_MAX` is fixed for all seven consumer repos.

- [ ] **Step 1: Merge Tasks 1–4 to main**

These must be on `main` because every consumer repo references the actions as `@main`.

- [ ] **Step 2: Re-run a failed autodeploy on an OSSRH repo**

```bash
command gh run list -R infinum/android-common-view -w "Update Version and Changelog" -L 1
command gh run rerun -R infinum/android-common-view <run-id>
```

- [ ] **Step 3: Confirm the failure moved downstream**

```bash
command gh api repos/infinum/android-common-view/actions/runs/<run-id>/jobs \
  --jq '.jobs[].steps[] | "\(.number) \(.conclusion) \(.name)"'
```

Expected: step 6 `Run predeploy steps using version.properties` is now **success**; step 7 `Deploy` is **failure** with OSSRH **HTTP 402**.

This is a PASS. The 402 is the pre-existing dead-OSSRH problem, not a regression — those six repos cannot reach the push step at all.

- [ ] **Step 4: Re-run a failed autodeploy on the pilot**

```bash
command gh run list -R infinum/android-common-kotlin -w "Update Version and Changelog" -L 1
command gh run rerun -R infinum/android-common-kotlin <run-id>
```

Expected: step 6 **success**, step 7 `Deploy` **success** (stages locally, reaches nothing), step 8 `Commit and push changes` **failure** with `GH013`.

This is a PASS, and it restores the original known failure.

- [ ] **Step 5: Record the outcome**

Note both run IDs in the PR description for Tasks 1–4. If either repo still fails at step 6 with `Argument list too long`, stop and re-open Task 1.

---

### Task 6: Resolve the base version from GitHub Releases

**Files:**
- Create: `scripts/resolve-base-version.sh`
- Create: `scripts/tests/test_resolve_base_version.sh`
- Create: `.github/actions/resolve_base_version/action.yml`
- Modify: `.github/workflows/test-scripts.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/resolve-base-version.sh` reads a GitHub Releases JSON array on **stdin** and prints exactly two lines, `base_tag=<v-prefixed tag or empty>` and `base_version=<x.y.z, or 0.0.0 when there is no release>`. The composite action `resolve_base_version` exposes them as outputs `base_tag` and `base_version`, and takes inputs `github_token` (required) and `repository` (defaults to `${{ github.repository }}`).

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_resolve_base_version.sh`:

```bash
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

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all resolve-base-version tests passed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash scripts/tests/test_resolve_base_version.sh`
Expected: FAIL — `resolve-base-version.sh: No such file or directory`

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/resolve-base-version.sh`:

```bash
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash scripts/tests/test_resolve_base_version.sh`
Expected: PASS — 9 `ok` lines, then `all resolve-base-version tests passed`

- [ ] **Step 5: Create the composite action**

Create `.github/actions/resolve_base_version/action.yml`:

```yaml
name: 'Resolve base version'
description: 'Resolves the highest released version from the GitHub Releases API'

inputs:
  github_token:
    description: 'The GitHub token'
    required: true
  repository:
    description: 'The repository to read releases from, as owner/name'
    required: false
    default: ${{ github.repository }}

outputs:
  base_tag:
    description: 'Tag of the highest release, empty when there is none'
    value: ${{ steps.resolve.outputs.base_tag }}
  base_version:
    description: 'Version of the highest release, 0.0.0 when there is none'
    value: ${{ steps.resolve.outputs.base_version }}

runs:
  using: 'composite'
  steps:
    - name: Locate scripts
      shell: bash
      run: echo "SCRIPTS_DIR=$(cd "$GITHUB_ACTION_PATH/../../../scripts" && pwd)" >> "$GITHUB_ENV"

    - name: Resolve base version
      id: resolve
      shell: bash
      env:
        GH_TOKEN: ${{ inputs.github_token }}
        REPO: ${{ inputs.repository }}
      run: |
        set -euo pipefail
        gh api "repos/$REPO/releases" --paginate --slurp \
          | jq 'flatten(1)' > "$RUNNER_TEMP/releases.json"
        bash "$SCRIPTS_DIR/resolve-base-version.sh" \
          < "$RUNNER_TEMP/releases.json" \
          | tee -a "$GITHUB_OUTPUT"
```

Note on the shape: `--paginate` alone emits one JSON array *per page*, which is not a single
valid JSON document. `--slurp` wraps them into an outer array, giving `[[rel, rel], [rel]]` —
an array of arrays, **not** a flat list. `jq 'flatten(1)'` collapses it to the flat
`[rel, rel, rel]` the script expects, and correctly yields `[]` when there are no releases.

- [ ] **Step 6: Wire the test into CI**

In `.github/workflows/test-scripts.yml`, add after the `Run gather-deps.sh test` step:

```yaml
      - name: Run resolve-base-version.sh test
        run: bash scripts/tests/test_resolve_base_version.sh
```

- [ ] **Step 7: Commit**

```bash
git add scripts/resolve-base-version.sh scripts/tests/test_resolve_base_version.sh \
        .github/actions/resolve_base_version .github/workflows/test-scripts.yml
git commit -m "feat: resolve the base version from GitHub Releases

Replaces reading version.properties. Drafts and prereleases are excluded
and ordering uses sort -V, so v2.2.3 sorts below v12.1.3. Deliberately
avoids /releases/latest, which orders by publication date and would
regress the version after a patch on an older line."
```

---

### Task 7: Guard against republishing an existing Central version

Covers the "deploy succeeded, record failed" retry: on the next run the version is already on Central, so the publish must be skipped rather than attempted again.

**Files:**
- Create: `scripts/check-central-published.sh`
- Create: `scripts/tests/test_check_central_published.sh`
- Create: `.github/actions/check_central_published/action.yml`
- Modify: `.github/workflows/test-scripts.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/check-central-published.sh <group> <version> <artifact>...` prints exactly one line, `published=true` or `published=false`. True only when **every** artifact is present. Honours `MAVEN_CENTRAL_BASE_URL` (default `https://repo1.maven.org/maven2`). The composite action `check_central_published` takes inputs `group`, `version`, `artifacts` (space-separated) and exposes output `published`.

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_check_central_published.sh`:

```bash
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash scripts/tests/test_check_central_published.sh`
Expected: FAIL — `check-central-published.sh: No such file or directory`

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/check-central-published.sh`:

```bash
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
  if ! curl -sfI --max-time 30 "$url" >/dev/null 2>&1; then
    echo "published=false"
    exit 0
  fi
done

echo "published=true"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash scripts/tests/test_check_central_published.sh`
Expected: PASS — 6 `ok` lines, then `all check-central-published tests passed`

- [ ] **Step 5: Verify the true path against real Maven Central**

Run: `bash scripts/check-central-published.sh com.infinum.android.common 0.2.0 kotlin`
Expected: `published=true` — this coordinate genuinely exists.

Run: `bash scripts/check-central-published.sh com.infinum.android.common 0.3.0 kotlin`
Expected: `published=false` — 0.3.0 was never published.

- [ ] **Step 6: Create the composite action**

Create `.github/actions/check_central_published/action.yml`:

```yaml
name: 'Check Maven Central publication'
description: 'Reports whether every artifact of a version is already on Maven Central'

inputs:
  group:
    description: 'Maven group id, e.g. com.infinum.android.common'
    required: true
  version:
    description: 'Version to check'
    required: true
  artifacts:
    description: 'Space-separated artifact ids'
    required: true

outputs:
  published:
    description: 'true when every artifact is already present'
    value: ${{ steps.check.outputs.published }}

runs:
  using: 'composite'
  steps:
    - name: Locate scripts
      shell: bash
      run: echo "SCRIPTS_DIR=$(cd "$GITHUB_ACTION_PATH/../../../scripts" && pwd)" >> "$GITHUB_ENV"

    - name: Check Maven Central
      id: check
      shell: bash
      env:
        GROUP: ${{ inputs.group }}
        VERSION: ${{ inputs.version }}
        ARTIFACTS: ${{ inputs.artifacts }}
      run: |
        set -euo pipefail
        # shellcheck disable=SC2086
        bash "$SCRIPTS_DIR/check-central-published.sh" "$GROUP" "$VERSION" $ARTIFACTS \
          | tee -a "$GITHUB_OUTPUT"
```

- [ ] **Step 7: Wire the test into CI**

In `.github/workflows/test-scripts.yml`, add after the resolve-base-version test step:

```yaml
      - name: Run check-central-published.sh test
        run: bash scripts/tests/test_check_central_published.sh
```

- [ ] **Step 8: Commit**

```bash
git add scripts/check-central-published.sh scripts/tests/test_check_central_published.sh \
        .github/actions/check_central_published .github/workflows/test-scripts.yml
git commit -m "feat: add a Maven Central publication guard

Makes the pipeline converge when a run publishes to Central but dies
before creating the GitHub release: the retry sees the version is already
there and skips the publish instead of failing on immutable coordinates."
```

---

### Task 8: Compose the file-free predeploy chain

**Files:**
- Create: `.github/actions/common_modules_predeploy_release/action.yml`

**Interfaces:**
- Consumes: `resolve_base_version` (Task 6) outputs `base_tag`, `base_version`; `commits_since_tag` (Task 4) output `commits`; the unchanged `find_pull_requests` output `pr_numbers`; `get_pull_request_details` (Task 1) outputs `pr_details`, `is_breaking_change`, `is_new_feature`, `is_bugfix`; the unchanged `update_version` output `updated_version`; the unchanged `generate_changelog` output `changelog`.
- Produces: outputs `base_tag`, `base_version`, `updated_version`, `changelog`, `pr_numbers`, `pr_details`. Writes no files. Task 9 and Task 12 consume these.

- [ ] **Step 1: Create the composite action**

Create `.github/actions/common_modules_predeploy_release/action.yml`:

```yaml
name: 'Predeploy for tag-derived releases'
description: 'Resolves the base version from GitHub Releases, computes the next version and generates the changelog. Writes no files.'

inputs:
  github_token:
    description: 'The GitHub token'
    required: true

outputs:
  base_tag:
    description: 'Tag of the release the next version is computed from'
    value: ${{ steps.resolve.outputs.base_tag }}
  base_version:
    description: 'Version of that release, 0.0.0 when there is none'
    value: ${{ steps.resolve.outputs.base_version }}
  updated_version:
    description: 'The computed next version'
    value: ${{ steps.update_version.outputs.updated_version }}
  changelog:
    description: 'The generated changelog'
    value: ${{ steps.generate_changelog.outputs.changelog }}
  pr_numbers:
    description: 'Pull request numbers since the base release'
    value: ${{ steps.get_pull_requests.outputs.pr_numbers }}
  pr_details:
    description: 'Pull request details since the base release'
    value: ${{ steps.get_pr_details.outputs.pr_details }}

runs:
  using: 'composite'
  steps:
    - name: Resolve base version from releases
      id: resolve
      uses: infinum/android-github-actions-workflows/.github/actions/resolve_base_version@main
      with:
        github_token: ${{ inputs.github_token }}

    - name: Get commits since the base release
      id: get_commits
      uses: infinum/android-github-actions-workflows/.github/actions/commits_since_tag@main
      with:
        tag: ${{ steps.resolve.outputs.base_tag }}

    - name: Get pull requests for commits
      id: get_pull_requests
      if: steps.get_commits.outputs.commits
      uses: infinum/android-github-actions-workflows/.github/actions/find_pull_requests@main
      with:
        commits: ${{ steps.get_commits.outputs.commits }}
        github_token: ${{ inputs.github_token }}

    - name: Get pull request details
      id: get_pr_details
      if: steps.get_pull_requests.outputs.pr_numbers
      uses: infinum/android-github-actions-workflows/.github/actions/get_pull_request_details@main
      with:
        pr_numbers: ${{ steps.get_pull_requests.outputs.pr_numbers }}
        github_token: ${{ inputs.github_token }}

    - name: Compute the next version
      id: update_version
      if: steps.get_pull_requests.outputs.pr_numbers && steps.get_pr_details.outputs.pr_details != '[]'
      uses: infinum/android-github-actions-workflows/.github/actions/update_version@main
      with:
        current_version: ${{ steps.resolve.outputs.base_version }}
        breaking_change: ${{ steps.get_pr_details.outputs.is_breaking_change }}
        new_feature: ${{ steps.get_pr_details.outputs.is_new_feature }}
        bugfix: ${{ steps.get_pr_details.outputs.is_bugfix }}

    - name: Generate the changelog
      id: generate_changelog
      if: steps.get_pull_requests.outputs.pr_numbers && steps.get_pr_details.outputs.pr_details != '[]'
      uses: infinum/android-github-actions-workflows/.github/actions/generate_changelog@main
      with:
        pr_details: ${{ steps.get_pr_details.outputs.pr_details }}
        current_version: ${{ steps.resolve.outputs.base_version }}
        updated_version: ${{ steps.update_version.outputs.updated_version }}
```

Note: there is deliberately **no** `update_changelog` step. Nothing writes `CHANGELOG.md`, because nothing writes to the branch.

- [ ] **Step 2: Verify no file-writing action is referenced**

Run:
```bash
grep -nE "update_changelog|write_updated_version|read_current_version|find_current_tag|push_version" \
  .github/actions/common_modules_predeploy_release/action.yml
```
Expected: no matches.

- [ ] **Step 3: Verify the YAML parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/actions/common_modules_predeploy_release/action.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add .github/actions/common_modules_predeploy_release
git commit -m "feat: add file-free predeploy chain for tag-derived releases

Same bump and changelog logic as common_modules_predeploy, but the base
version comes from GitHub Releases rather than version.properties and
nothing is written to disk."
```

---

### Task 9: Rehearsal pipeline in the test-setup repo

Repo: `infinum/android-common-projects-test-setup`, default branch `master`.

**Files:**
- Modify: `build.gradle.kts` (the `version = ...` line)
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: `common_modules_predeploy_release` (Task 8), `check_central_published` (Task 7), `create_github_release` (Task 3).
- Produces: a runnable rehearsal workflow with two boolean inputs, `dry_run` (default `true`) and `fail_injection` (default `false`).

- [ ] **Step 1: Replace the version line in build.gradle.kts**

Find the existing line:
```kotlin
version = Properties().apply { load(FileInputStream("version.properties")) }.getProperty("version")
```

Replace it with:
```kotlin
// The release version is supplied by CI as -PreleaseVersion=<x.y.z>, derived from
// the last GitHub Release. Publishing without it is a hard error: a silently
// defaulted version could ship wrong coordinates to Maven Central. Non-publish
// builds get a placeholder so IDE sync and ./gradlew test keep working.
val isPublishing = gradle.startParameter.taskNames.any { it.contains("publish", ignoreCase = true) }

version = providers.gradleProperty("releaseVersion").orNull
    ?: if (isPublishing) {
        error("Publishing requires -PreleaseVersion=<x.y.z>. CI supplies this; " +
              "locally, decide the version deliberately.")
    } else {
        "0.0.0-LOCAL"
    }
```

Remove the now-unused `java.io.FileInputStream` and `java.util.Properties` imports if nothing else uses them.

- [ ] **Step 2: Verify the three version paths locally**

```bash
./gradlew help -q                                   # expect: success
./gradlew publishToMavenLocal 2>&1 | grep -c "requires -PreleaseVersion"   # expect: 1
./gradlew publishToMavenLocal -PreleaseVersion=9.9.9 -q                     # expect: success
ls ~/.m2/repository/com/infinum/android/common/common-modules-test/9.9.9/
```
Expected: the first succeeds, the second fails with the explicit message, the third publishes 9.9.9 locally.

- [ ] **Step 3: Create the rehearsal workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

# Rehearsal only. Deploy is pinned to publishToMavenLocal and must never point
# at Maven Central from this repo: its android module publishes as
# common-modules-test, which has never been on Central, and a real publish
# would put a permanent junk version there.
on:
  workflow_dispatch:
    inputs:
      dry_run:
        type: boolean
        default: true
        description: "Resolve and build, but create no tag and no release."
      fail_injection:
        type: boolean
        default: false
        description: "Force the deploy step to fail, to prove no tag or release is created."

concurrency:
  group: release
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v6
        with:
          fetch-depth: 0

      - name: Set up JDK
        uses: actions/setup-java@v5
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Cache Gradle wrapper
        uses: infinum/android-github-actions-workflows/.github/actions/cache_gradle_wrapper@main

      - name: Cache Gradle dependencies
        uses: infinum/android-github-actions-workflows/.github/actions/cache_gradle@main

      - name: Resolve version and changelog
        id: predeploy
        uses: infinum/android-github-actions-workflows/.github/actions/common_modules_predeploy_release@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}

      - name: Report the resolved release
        env:
          BASE_TAG: ${{ steps.predeploy.outputs.base_tag }}
          BASE_VERSION: ${{ steps.predeploy.outputs.base_version }}
          NEXT_VERSION: ${{ steps.predeploy.outputs.updated_version }}
          PR_NUMBERS: ${{ steps.predeploy.outputs.pr_numbers }}
        run: |
          {
            echo "### Resolved release"
            echo ""
            echo "| field | value |"
            echo "|---|---|"
            echo "| base tag | \`${BASE_TAG:-none}\` |"
            echo "| base version | \`$BASE_VERSION\` |"
            echo "| next version | \`${NEXT_VERSION:-none — nothing to release}\` |"
            echo "| pull requests | \`${PR_NUMBERS:-none}\` |"
          } >> "$GITHUB_STEP_SUMMARY"

      - name: Check whether the version is already published
        id: guard
        if: steps.predeploy.outputs.updated_version
        uses: infinum/android-github-actions-workflows/.github/actions/check_central_published@main
        with:
          group: com.infinum.android.common
          version: ${{ steps.predeploy.outputs.updated_version }}
          artifacts: common-modules-test

      - name: Deploy
        id: deploy
        if: steps.predeploy.outputs.updated_version && steps.guard.outputs.published != 'true'
        env:
          FAIL_INJECTION: ${{ inputs.fail_injection }}
          RELEASE_VERSION: ${{ steps.predeploy.outputs.updated_version }}
        run: |
          set -euo pipefail
          if [ "$FAIL_INJECTION" = "true" ]; then
            echo "Deploy failure injected on purpose; no tag or release must follow."
            exit 1
          fi
          ./gradlew publishToMavenLocal -PreleaseVersion="$RELEASE_VERSION" --no-parallel

      - name: Create tag and release
        if: >-
          steps.predeploy.outputs.updated_version &&
          inputs.dry_run != true
        uses: infinum/android-github-actions-workflows/.github/actions/create_github_release@main
        with:
          updated_version: ${{ steps.predeploy.outputs.updated_version }}
          changelog: ${{ steps.predeploy.outputs.changelog }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          target_commitish: ${{ github.sha }}
```

The `Create tag and release` step carries no `if: success()`. Actions steps are fail-fast and sequential, so a failing deploy skips it structurally — that is the constraint, and it cannot be broken by editing a condition.

- [ ] **Step 4: Verify the YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit and push to master**

```bash
git add build.gradle.kts .github/workflows/release.yml
git commit -m "feat: add tag-derived release rehearsal workflow

Dispatch-only. Deploy is pinned to publishToMavenLocal — this repo must
never publish to real Maven Central. fail_injection forces the deploy to
fail so we can prove no tag or release is created."
git push origin HEAD
```

---

### Task 10: GATE — run the rehearsal

No code. This is where the deploy-then-tag constraint is actually proven. **Do not proceed to the pilot until run 3 passes.**

**Files:** none.

**Interfaces:**
- Consumes: Task 9, on `master` in `infinum/android-common-projects-test-setup`.
- Produces: evidence that a failed deploy creates no tag and no release, and that the next run retries the same version.

- [ ] **Step 1: Run 1 — resolution only**

```bash
command gh workflow run release.yml -R infinum/android-common-projects-test-setup \
  -f dry_run=true -f fail_injection=false
```

Expected in the job summary: base tag `v0.7.3`, base version `0.7.3`, next version `none — nothing to release` (there are no commits since the tag). Nothing created.

Verify: `command gh api repos/infinum/android-common-projects-test-setup/releases --jq '[.[].tag_name]'` still ends at `v0.7.3`.

- [ ] **Step 2: Merge a labelled PR to create something to release**

Open a trivial PR against `master` (for example a README line), label it `bugfix`, and merge it.

- [ ] **Step 3: Run 2 — a real rehearsal release**

```bash
command gh workflow run release.yml -R infinum/android-common-projects-test-setup \
  -f dry_run=false -f fail_injection=false
```

Expected: next version `0.7.4` (a `bugfix` label bumps the patch). Deploy succeeds. **Tag `v0.7.4` and release `v0.7.4` both exist.**

Verify both were created by the one call:
```bash
command gh api repos/infinum/android-common-projects-test-setup/tags --jq '[.[].name][0:3]'
command gh api repos/infinum/android-common-projects-test-setup/releases --jq '[.[].tag_name][0:3]'
```

- [ ] **Step 4: Merge a second labelled PR**

Same as Step 2, so there is again something to release.

- [ ] **Step 5: Run 3 — THE CONSTRAINT TEST**

```bash
command gh workflow run release.yml -R infinum/android-common-projects-test-setup \
  -f dry_run=false -f fail_injection=true
```

Expected: the workflow **fails** at `Deploy`. The `Create tag and release` step is **skipped**.

Verify nothing was created:
```bash
command gh api repos/infinum/android-common-projects-test-setup/tags --jq '[.[].name][0:3]'
command gh api repos/infinum/android-common-projects-test-setup/releases --jq '[.[].tag_name][0:3]'
```
Expected: both still end at `v0.7.4`. **If a `v0.7.5` tag or release exists, the constraint is broken — stop and fix before going near the pilot.**

- [ ] **Step 6: Run 4 — retry after the injected failure**

```bash
command gh workflow run release.yml -R infinum/android-common-projects-test-setup \
  -f dry_run=false -f fail_injection=false
```

Expected: base version is still `0.7.4`, next version is `0.7.5`, deploy succeeds, tag and release `v0.7.5` are created. This is the redeploy-after-failure behaviour.

- [ ] **Step 7: Record the evidence**

Note all four run URLs. They are the proof for the pilot's review.

---

### Task 11: Pilot build change

Repo: `infinum/android-common-kotlin`.

**Files:**
- Modify: `build.gradle.kts:7`
- Modify: `version.properties` (header comment only)
- Modify: `CHANGELOG.md` (header comment only)

**Interfaces:**
- Consumes: the pattern proven in Task 9 Step 1.
- Produces: a build that takes its version from `-PreleaseVersion` and refuses to publish without it.

- [ ] **Step 1: Replace the version line**

In `build.gradle.kts`, replace line 7:
```kotlin
version = Properties().apply { load(file("version.properties").inputStream()) }.getProperty("version")
```

with:
```kotlin
// The release version is supplied by CI as -PreleaseVersion=<x.y.z>, derived from
// the last GitHub Release. Publishing without it is a hard error: a silently
// defaulted version could ship wrong coordinates to Maven Central. Non-publish
// builds get a placeholder so IDE sync and ./gradlew test keep working.
val isPublishing = gradle.startParameter.taskNames.any { it.contains("publish", ignoreCase = true) }

version = providers.gradleProperty("releaseVersion").orNull
    ?: if (isPublishing) {
        error("Publishing requires -PreleaseVersion=<x.y.z>. CI supplies this; " +
              "locally, decide the version deliberately.")
    } else {
        "0.0.0-LOCAL"
    }
```

Remove the now-unused `import java.util.Properties` if nothing else uses it.

- [ ] **Step 2: Mark the two deferred files as unmaintained**

Prepend to `version.properties`:
```
# Not maintained during the release-flow migration. The published version comes
# from the last GitHub Release; see docs/superpowers/specs in
# infinum/android-github-actions-workflows. This file is deleted after review.
```

Prepend to `CHANGELOG.md`:
```
> **Not maintained during the release-flow migration.** Release notes live in
> GitHub Releases. This file is deleted after review.

```

- [ ] **Step 3: Verify the three version paths**

```bash
./gradlew help -q                                                          # expect: success
./gradlew publishToMavenLocal 2>&1 | grep -c "requires -PreleaseVersion"   # expect: 1
./gradlew publishToMavenLocal -PreleaseVersion=9.9.9 -q                    # expect: success
ls ~/.m2/repository/com/infinum/android/common/kotlin/9.9.9/
```
Expected: the directory lists a `.pom`, a `.jar`, a sources jar and a javadoc jar at `9.9.9`.

- [ ] **Step 4: Verify the existing build still works**

Run: `./gradlew build -q`
Expected: success. This confirms the `isPublishing` guard does not fire on ordinary builds.

- [ ] **Step 5: Clean up the local artifact**

```bash
rm -rf ~/.m2/repository/com/infinum/android/common/kotlin/9.9.9
```

- [ ] **Step 6: Open a PR**

```bash
git checkout -b feature/tag-derived-version
git add build.gradle.kts version.properties CHANGELOG.md
git commit -m "feat: take the release version from -PreleaseVersion

The version now comes from CI, derived from the last GitHub Release,
rather than from version.properties. Publishing without an explicit
version is a hard error so a defaulted value can never reach Maven
Central; ordinary builds and IDE sync get a 0.0.0-LOCAL placeholder.

version.properties and CHANGELOG.md are kept but marked unmaintained;
they are deleted in a follow-up once the migration is reviewed."
git push -u origin HEAD
command gh pr create --fill
```

SonarCloud, Bitrise and Danger must all pass before merging.

---

### Task 12: Pilot release workflow

Repo: `infinum/android-common-kotlin`.

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: Task 8, Task 7, Task 3, and the build change from Task 11.
- Produces: a dispatch-only release pipeline with a `dry_run` input, defaulting to `true`.

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  workflow_dispatch:
    inputs:
      dry_run:
        type: boolean
        default: true
        description: "Resolve and build locally, but publish nothing and create no tag or release."

concurrency:
  group: release
  cancel-in-progress: false

# contents: write creates the tag and release.
# actions: write dispatches the Pages rebuild, since a release created with
# GITHUB_TOKEN emits no release:published event to trigger it.
permissions:
  contents: write
  actions: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7
        with:
          fetch-depth: 0

      - name: Set up JDK
        uses: actions/setup-java@v6
        with:
          java-version: '25.0.4+101.0.LTS'
          distribution: 'temurin'

      - name: Cache Gradle wrapper
        uses: infinum/android-github-actions-workflows/.github/actions/cache_gradle_wrapper@main

      - name: Cache Gradle dependencies
        uses: infinum/android-github-actions-workflows/.github/actions/cache_gradle@main

      - name: Resolve version and changelog
        id: predeploy
        uses: infinum/android-github-actions-workflows/.github/actions/common_modules_predeploy_release@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}

      - name: Report the resolved release
        env:
          BASE_TAG: ${{ steps.predeploy.outputs.base_tag }}
          BASE_VERSION: ${{ steps.predeploy.outputs.base_version }}
          NEXT_VERSION: ${{ steps.predeploy.outputs.updated_version }}
          PR_NUMBERS: ${{ steps.predeploy.outputs.pr_numbers }}
        run: |
          {
            echo "### Resolved release"
            echo ""
            echo "| field | value |"
            echo "|---|---|"
            echo "| base tag | \`${BASE_TAG:-none}\` |"
            echo "| base version | \`$BASE_VERSION\` |"
            echo "| next version | \`${NEXT_VERSION:-none — nothing to release}\` |"
            echo "| pull requests | \`${PR_NUMBERS:-none}\` |"
          } >> "$GITHUB_STEP_SUMMARY"

      - name: Check whether the version is already published
        id: guard
        if: steps.predeploy.outputs.updated_version
        uses: infinum/android-github-actions-workflows/.github/actions/check_central_published@main
        with:
          group: com.infinum.android.common
          version: ${{ steps.predeploy.outputs.updated_version }}
          artifacts: kotlin

      - name: Deploy (dry run — local only)
        if: >-
          steps.predeploy.outputs.updated_version &&
          steps.guard.outputs.published != 'true' &&
          inputs.dry_run == true
        run: ./gradlew publishToMavenLocal -PreleaseVersion=${{ steps.predeploy.outputs.updated_version }} --no-parallel

      - name: Deploy to Maven Central
        if: >-
          steps.predeploy.outputs.updated_version &&
          steps.guard.outputs.published != 'true' &&
          inputs.dry_run != true
        run: ./gradlew publishAndReleaseToMavenCentral -PreleaseVersion=${{ steps.predeploy.outputs.updated_version }} --no-parallel
        env:
          ORG_GRADLE_PROJECT_mavenCentralUsername: ${{ secrets.MAVEN_CENTRAL_USER }}
          ORG_GRADLE_PROJECT_mavenCentralPassword: ${{ secrets.MAVEN_CENTRAL_PW }}
          ORG_GRADLE_PROJECT_signingInMemoryKey: ${{ secrets.DEPLOY_IN_MEMORY_SIGNING_KEY }}
          ORG_GRADLE_PROJECT_signingInMemoryKeyPassword: ${{ secrets.DEPLOY_IN_MEMORY_SIGNING_PASSWORD }}

      - name: Create tag and release
        id: record
        if: >-
          steps.predeploy.outputs.updated_version &&
          inputs.dry_run != true
        uses: infinum/android-github-actions-workflows/.github/actions/create_github_release@main
        with:
          updated_version: ${{ steps.predeploy.outputs.updated_version }}
          changelog: ${{ steps.predeploy.outputs.changelog }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          target_commitish: ${{ github.sha }}

      - name: Rebuild the documentation site
        if: steps.record.outcome == 'success' && inputs.dry_run != true
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: gh workflow run static.yml --ref "${{ github.ref_name }}"
```

The Pages rebuild is dispatched explicitly because a release created with `GITHUB_TOKEN` emits no `release: published` event.

`publishAndReleaseToMavenCentral` — not `publishMavenPublicationToMavenCentralRepository` — is what makes this step a real gate. The latter stages files locally, prints `Skipping deployment validation!` and exits 0 without publishing anything.

- [ ] **Step 2: Verify the YAML parses**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Verify autodeploy.yml is untouched**

Run: `git status --short .github/workflows/`
Expected: only `release.yml` is new. `autodeploy.yml` must not be modified or deleted yet.

- [ ] **Step 4: Open a PR**

```bash
git checkout -b feature/tag-derived-release-workflow
git add .github/workflows/release.yml
git commit -m "feat: add dispatch-only tag-derived release workflow

Runs alongside the existing autodeploy.yml, which stays in place until
this path has proven itself. Nothing writes to main: the version comes
from the last GitHub Release, and the tag and release are created by a
single API call only after publishAndReleaseToMavenCentral succeeds."
git push -u origin HEAD
command gh pr create --fill
```

---

### Task 13: GATE — pilot dry run

No code.

**Files:** none.

**Interfaces:**
- Consumes: Tasks 11 and 12, merged to `main` in `infinum/android-common-kotlin`.
- Produces: confirmation that the 26-PR backlog resolves without `ARG_MAX` and that the computed version is correct.

- [ ] **Step 1: Dispatch the dry run**

```bash
command gh workflow run release.yml -R infinum/android-common-kotlin -f dry_run=true
```

- [ ] **Step 2: Check the job summary**

| field | expected |
|---|---|
| base tag | `v0.2.0` |
| base version | `0.2.0` |
| next version | `0.3.0` |
| pull requests | 26 numbers, no truncation |

- [ ] **Step 3: Confirm no ARG_MAX failure**

```bash
command gh run view <run-id> -R infinum/android-common-kotlin --log | grep -c "Argument list too long"
```
Expected: `0`

- [ ] **Step 4: Confirm the guard reported false**

The `Check whether the version is already published` step must output `published=false` — `0.3.0` is not on Central.

- [ ] **Step 5: Confirm nothing was created**

```bash
command gh api repos/infinum/android-common-kotlin/tags --jq '[.[].name]'
command gh api repos/infinum/android-common-kotlin/releases --jq '[.[].tag_name]'
```
Expected: tags still `v0.2.0 v0.1.0 v0.0.1`; releases still `v0.2.0 v0.1.0`.

---

### Task 14: GATE — first real release

No code. **This is the irreversible step.** A published Maven Central version cannot be withdrawn.

**Files:** none.

**Interfaces:**
- Consumes: Task 13 passing.
- Produces: `com.infinum.android.common:kotlin:0.3.0` on Maven Central, plus tag and release `v0.3.0`.

- [ ] **Step 1: Confirm the credentials are Central Portal tokens**

Ask the repository owner to confirm `MAVEN_CENTRAL_USER` / `MAVEN_CENTRAL_PW` are Central **Portal** tokens, not OSSRH. They are org-level secrets shared with six repos still pointed at dead OSSRH. If they are OSSRH credentials, this step fails — safely, with no tag and no release.

- [ ] **Step 2: Dispatch the real release**

```bash
command gh workflow run release.yml -R infinum/android-common-kotlin -f dry_run=false
```

- [ ] **Step 3: If the deploy fails on a stuck Portal deployment**

A `0.3.0` deployment may be stranded in the Portal from the 2026-07-03 run. If the deploy fails for that reason:

1. **Do not drop it yourself.** Report the failure to the repository owner.
2. Confirm no tag and no release were created — this is the constraint holding.
3. Once the owner has dropped the deployment, re-run Step 2.

- [ ] **Step 4: Verify the tag and release were created together**

```bash
command gh api repos/infinum/android-common-kotlin/tags --jq '[.[].name][0:2]'
command gh api repos/infinum/android-common-kotlin/releases --jq '[.[].tag_name][0:2]'
```
Expected: both now start with `v0.3.0`.

- [ ] **Step 5: Verify Maven Central, allowing for propagation**

```bash
curl -s https://repo1.maven.org/maven2/com/infinum/android/common/kotlin/maven-metadata.xml
```
Expected: `0.3.0` appears in the version list. Allow 10–30 minutes for propagation before treating absence as a failure.

- [ ] **Step 6: Verify the Pages rebuild was dispatched**

```bash
command gh run list -R infinum/android-common-kotlin -w "Deploy static content to Pages" -L 1
```
Expected: a run triggered by `workflow_dispatch` shortly after the release.

---

### Task 15: Cutover

Repo: `infinum/android-common-kotlin`.

**Files:**
- Modify: `.github/workflows/release.yml` (add the `push` trigger)
- Delete: `.github/workflows/autodeploy.yml`

**Interfaces:**
- Consumes: Task 14 passing.
- Produces: automatic releases on merge to `main`, with the old flow gone.

- [ ] **Step 1: Add the push trigger**

In `.github/workflows/release.yml`, replace the `on:` block with:

```yaml
on:
  push:
    branches:
      - main
  workflow_dispatch:
    inputs:
      dry_run:
        type: boolean
        default: true
        description: "Resolve and build locally, but publish nothing and create no tag or release."
```

On a `push` event `inputs.dry_run` is unset, so `inputs.dry_run != true` is satisfied and `inputs.dry_run == true` is not. Pushes therefore take the real path, and dispatches default to a dry run.

- [ ] **Step 2: Delete the old workflow**

```bash
git rm .github/workflows/autodeploy.yml
```

- [ ] **Step 3: Open a PR and merge**

```bash
git checkout -b feature/release-cutover
git add .github/workflows/release.yml
git commit -m "feat: cut over to the tag-derived release workflow

release.yml now runs on merges to main and autodeploy.yml is removed.
Dispatches still default to a dry run."
git push -u origin HEAD
command gh pr create --fill
```

- [ ] **Step 4: Verify the skip path with a labelled PR**

Open a trivial PR, label it `skip-release`, and merge it. The release workflow must run and create **nothing** — no publish, no tag, no release.

```bash
command gh api repos/infinum/android-common-kotlin/releases --jq '[.[].tag_name][0:2]'
```
Expected: unchanged.

- [ ] **Step 5: Verify the normal path**

Merge an ordinary PR with a `bugfix` label. Expected: `0.3.1` published, tag and release created together.

---

### Task 16: Changelog on the documentation site

Repo: `infinum/android-common-kotlin`.

**Files:**
- Create: `scripts/render-changelog.sh` *(in `infinum/android-github-actions-workflows`)*
- Create: `scripts/tests/test_render_changelog.sh` *(same repo)*
- Modify: `.github/workflows/static.yml` *(in `infinum/android-common-kotlin`)*
- Modify: `.github/workflows/test-scripts.yml` *(shared repo)*

**Interfaces:**
- Consumes: the Releases API.
- Produces: `scripts/render-changelog.sh` reads a Releases JSON array on **stdin** and writes Markdown to stdout: one `## <tag_name>` heading per release, newest first, followed by that release's body. Drafts are excluded.

- [ ] **Step 1: Write the failing test**

Create `scripts/tests/test_render_changelog.sh` in `infinum/android-github-actions-workflows`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/render-changelog.sh"
FAILURES=0

check() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -Fq "$needle"; then
    echo "ok   - $name"
  else
    echo "FAIL - $name: expected to find '$needle'"
    FAILURES=$((FAILURES + 1))
  fi
}

refute() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -Fq "$needle"; then
    echo "FAIL - $name: did not expect '$needle'"
    FAILURES=$((FAILURES + 1))
  else
    echo "ok   - $name"
  fi
}

INPUT='[
  {"tag_name":"v0.3.0","draft":false,"body":"### Changes\n- Something new"},
  {"tag_name":"v0.2.0","draft":false,"body":"### Changes\n- Something older"},
  {"tag_name":"v9.9.9","draft":true,"body":"unreleased"}
]'

OUTPUT="$(printf '%s' "$INPUT" | bash "$SCRIPT")"

check "renders the newest release heading" "$OUTPUT" "## v0.3.0"
check "renders the older release heading" "$OUTPUT" "## v0.2.0"
check "renders release bodies" "$OUTPUT" "- Something new"
refute "excludes drafts" "$OUTPUT" "v9.9.9"

FIRST_HEADING="$(printf '%s' "$OUTPUT" | grep '^## ' | head -1)"
if [ "$FIRST_HEADING" = "## v0.3.0" ]; then
  echo "ok   - newest release comes first"
else
  echo "FAIL - newest release should come first, got '$FIRST_HEADING'"
  FAILURES=$((FAILURES + 1))
fi

EMPTY_OUTPUT="$(printf '[]' | bash "$SCRIPT")"
check "empty release list still renders a title" "$EMPTY_OUTPUT" "# Changelog"

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed"
  exit 1
fi
echo "all render-changelog tests passed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash scripts/tests/test_render_changelog.sh`
Expected: FAIL — `render-changelog.sh: No such file or directory`

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/render-changelog.sh`:

```bash
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
set -euo pipefail

releases="$(cat)"

echo "# Changelog"
echo ""

printf '%s' "$releases" | jq -r '
  [ .[] | select(.draft | not) ]
  | sort_by(.published_at // .created_at // "")
  | reverse
  | .[]
  | "## \(.tag_name)\n\n\(.body // "_No release notes._")\n"
'
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash scripts/tests/test_render_changelog.sh`
Expected: PASS — 6 `ok` lines, then `all render-changelog tests passed`

- [ ] **Step 5: Wire the test into CI**

In `.github/workflows/test-scripts.yml`, add after the check-central-published test step:

```yaml
      - name: Run render-changelog.sh test
        run: bash scripts/tests/test_render_changelog.sh
```

- [ ] **Step 6: Commit the shared-repo half**

```bash
git add scripts/render-changelog.sh scripts/tests/test_render_changelog.sh \
        .github/workflows/test-scripts.yml
git commit -m "feat: render a changelog from GitHub Releases

The release flow no longer writes CHANGELOG.md, so the documentation site
renders release notes from the Releases API at build time instead."
```

- [ ] **Step 7: Add the render step to the pilot's Pages workflow**

In `infinum/android-common-kotlin`, in `.github/workflows/static.yml`, insert between `Generate documentation` and `Upload artifact`:

```yaml
      - name: Render the changelog
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          set -euo pipefail
          curl -fsSL \
            https://raw.githubusercontent.com/infinum/android-github-actions-workflows/main/scripts/render-changelog.sh \
            -o "$RUNNER_TEMP/render-changelog.sh"
          gh api "repos/${{ github.repository }}/releases" --paginate --slurp \
            | jq 'flatten(1)' \
            | bash "$RUNNER_TEMP/render-changelog.sh" > docs/changelog.md
```

`static.yml` has `permissions: contents: read`, which is sufficient to read releases on a public repository.

- [ ] **Step 8: Verify the rendered page**

```bash
command gh workflow run static.yml -R infinum/android-common-kotlin
```
Then confirm `docs/changelog.md` is in the uploaded Pages artifact and lists `v0.3.0` first.

- [ ] **Step 9: Commit the pilot half**

```bash
git checkout -b feature/pages-changelog
git add .github/workflows/static.yml
git commit -m "feat: publish the changelog to the documentation site

Release notes now live in GitHub Releases; the Pages build renders them
alongside the Dokka output."
git push -u origin HEAD
command gh pr create --fill
```

---

## After this plan

Two follow-ups, tracked separately and deliberately **not** in scope here:

1. **Phase 9 — delete the deferred files.** Once the tech lead has reviewed the migration, delete `version.properties` and `CHANGELOG.md` from `android-common-kotlin` in their own PR.
2. **Phase 10 — the other six repos.** `android`, `compose`, `coroutines`, `junit`, `ui` and `view` publish to OSSRH, which returns HTTP 402 since its 2025-06-30 sunset. Each needs an OSSRH → Central Portal migration *before* it can adopt this flow. One repo at a time, Portal migration as its own reviewed PR, reusing the actions this plan proves.
