# Tag-derived versioning for the Android common modules

**Date:** 2026-09-15
**Status:** Approved design, not yet implemented
**Scope:** `infinum/android-github-actions-workflows`, `infinum/android-common-*`

## Problem

The `Update Version and Changelog` workflow fails on all seven common modules. There
are two distinct failures, and a third latent defect.

### 1. The org ruleset blocks the push (since 2026-07-03)

```
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - Changes must be made through a pull request.
 ! [remote rejected] main -> main
```

The org ruleset `Main Branch Protection` (id `8879073`, source `infinum`, active since
2025-10-14) applies to `~DEFAULT_BRANCH` with a `pull_request` rule (1 approval,
`require_extra_approval_for_unattributed_changes: true`) and `non_fast_forward`.
`bypass_actors` is empty and `current_user_can_bypass` is `never`. The `git push` in
`push_version_update` can never succeed. The protection cannot be removed.

### 2. `Argument list too long` now masks it (since ~2026-08-17)

Because nothing has released since `v0.2.0`, `common_modules_predeploy` accumulates 26
PRs and passes their full bodies — including dumped Copilot prompt blocks — between
steps. This exceeds `ARG_MAX` before the push is ever reached.

`get_pull_request_details` puts `body` into `prData`, but `generate_changelog` only reads
`title`, `author`, `number` and `labels`. The field is dead weight.

### 3. The deploy step is not a reliable success gate

`publishMavenPublicationToMavenCentralRepository` stages files locally, prints
`Skipping deployment validation!` and exits 0 without validating or releasing the Central
Portal deployment. Confirmed twice:

- `android-common-kotlin` "successfully deployed" `0.3.0` on 2026-07-03; Central still
  holds only `0.1.0` and `0.2.0`.
- `android-common-projects-test-setup` has 15 releases; `com.infinum.android.common:common-modules-test`
  is 404 on `repo1.maven.org`.

Deploy also runs *before* the git push, so a publish can succeed while the version bump
and tag are lost.

### Out of scope, but blocking "everything green"

Two of seven repos (`junit`, `ui`) still
publish through legacy OSSRH at `https://oss.sonatype.org/service/local/staging/deploy/maven2`,
which returns **HTTP 402** — OSSRH was sunset 2025-06-30. They also run JDK 17,
Dokka V1, `checkout@v4`, `setup-java@v4`. The other five repos (`android`, `compose`,
`coroutines`, `kotlin`, `view`) are on vanniktech / Central Portal.

Those two need an OSSRH → Central Portal migration *in addition to* this work. It is
tracked separately.

**Corrected 2026-09-16:** an earlier revision of this document said *six* of seven repos
were on legacy OSSRH. That came from local clones that were a year stale. Checked against
the remote, the real split is **five on vanniktech / Central Portal** (`android`,
`compose`, `coroutines`, `kotlin`, `view`) and **two on legacy OSSRH** (`junit`, `ui`).
Phase 10 is therefore two repos, not six, and four repos beyond the pilot are ready for
tag-derived versioning as soon as it is proven.

## Design

Invert the version flow. Today `version.properties` determines the tag name. After this
change, the last GitHub Release determines the version, and the tag is written only after
a successful publish.

### Pipeline

On push to the default branch (trigger and `concurrency` group unchanged):

```
1. checkout            fetch-depth: 0, GITHUB_TOKEN (read only, no SSH key)
2. resolve base        Releases API -> filter draft/prerelease -> sort -V -> v0.2.0
3. collect             commits since v0.2.0 -> PR numbers -> labels
4. compute             next version -> 0.3.0
5. guard               already on Central? -> skip step 6
6. DEPLOY              ./gradlew publishAndReleaseToMavenCentral -PreleaseVersion=0.3.0
7+8. RECORD            POST /releases {tag_name, target_commitish, body}  <- atomic
```

Nothing writes to a branch. The org ruleset has `target: branch` and there is no tag
ruleset, so creating the tag is already permitted today.

### Why releases, not tags, are the source of truth

A GitHub Release is backed by a tag, so releases are a filtered view of tags rather than
an independent source. Using them means the base is "the last version we actually
announced" rather than "the last tag that exists" — a stray or hand-pushed tag cannot
shift the base, and drafts and prereleases are excluded for free.

Verified 2026-09-15: in all seven repos the highest tag equals the latest release. The
only divergence is `v0.0.1`, tagged everywhere and released nowhere. Both sources agree
today; this is future hardening, not a correction.

**Do not use `/releases/latest`** — it returns the most recently published release *by
date*, not the highest semver. A patch on an older line (0.2.1 after 0.3.0) would regress
the next version. Read the list and sort explicitly:

```bash
gh api repos/{owner}/{repo}/releases --paginate \
  --jq '[.[] | select(.draft|not) | select(.prerelease|not) | .tag_name]' \
  | sort -V | tail -1
```

`sort -V` compares digit runs numerically. Plain `sort` does not:

```
plain sort:   v0.0.1 v0.10.0 v0.2.0 v0.9.0 v1.0.0 v10.0.0 v12.1.3 v2.2.3   WRONG
sort -V:      v0.0.1 v0.2.0 v0.9.0 v0.10.0 v1.0.0 v2.2.3 v10.0.0 v12.1.3   CORRECT
```

`sort -V` is safe here precisely because prereleases are filtered out; it mis-orders
`1.0.0-rc1` against `1.0.0`, which this pipeline never sees. `git describe --tags
--abbrev=0` is *topological*, not semver-sorted, and has its own version of this bug.

The tag is still needed for the commit range — `commits_since_tag` diffs from a git ref,
and that ref is the release's `tag_name`. The Releases API only decides *which* tag to
trust.

### Transactionality

**Steps 7 and 8 are atomic.** `POST /repos/{owner}/{repo}/releases` accepts
`target_commitish`, documented as *"determines where the Git tag is created from… unused
if the Git tag already exists."* GitHub creates the tag and the release in one server-side
operation. `push_version_tag` is dropped entirely — nothing can create the tag without
the release, which also removes the "tag exists, release missing" state that
releases-as-source-of-truth would otherwise introduce.

Two consequences:
- No SSH key is needed. `GITHUB_TOKEN` with `contents: write` suffices, and
  `ROOT_GITHUB_ACTIONS_SSH` leaves the workflow.
- A release created by `GITHUB_TOKEN` emits **no** `release: published` event, so the
  Pages rebuild cannot hang off that trigger. It is invoked directly instead.

**Step 6 cannot join them, and should not.** A published Maven Central version is
permanently immutable; there is nothing to roll back. The design is convergence, not
atomicity, under a one-directional invariant:

> Central is the source of truth for what shipped. The release is a derived record that
> retries until it catches up.

This fixes the order as deploy → record, never the reverse.

| crash point | state | next run |
|---|---|---|
| during 6 | nothing on Central, no release | recomputes same version, retries cleanly |
| after 6, before 7+8 | on Central, no release | guard sees it, **skips publish**, records release |
| after 7+8 | consistent | proceeds to next version |

Recording before publishing would violate the deploy-then-tag constraint *and* advertise
a version that is not on Central.

**Known gap:** `publishAndReleaseToMavenCentral` returns once the Portal accepts and
releases the deployment, but propagation to `repo1.maven.org` lags roughly 10–30 minutes.
A retry inside that window misses the guard and fails on duplicate coordinates. Retries
are driven by the next merge to the default branch, so the window is almost never hit.
Accepted rather than adding Portal-API polling.

### Failure modes

- **Deploy fails** → no tag, no release. Base stays at the previous version; the next
  merge recomputes and retries the whole release. This is the required redeploy behaviour.
- **Deploy succeeds, record fails** → next run's guard sees the version on Central, skips
  the publish, records the release.
- **Orphaned Portal deployment** → surfaces as a deploy failure. `dropMavenCentralDeployment`
  is the escape hatch. **Never dropped automatically; always a human decision.**
- **No releases at all** → base defaults to `0.0.0`, first release is `0.1.0`.

## Components

Every action is referenced as `@main`, so edits to shared actions go live for all seven
repos on their next run. Changes are therefore split into *fixes* (safe in place, help
everyone) and *new flow* (new actions, so the pilot moves while the other six stay put).

### A. `infinum/android-github-actions-workflows`

Fixes in place:

| # | action | change |
|---|---|---|
| A1 | `get_pull_request_details/index.js` | Drop `body` from `prData`. Fixes `Argument list too long`. No build step — `index.js` and `node_modules` are committed. |
| A2 | `create_github_release/index.js` | Add `target_commitish`; treat `422 already_exists` as success. Makes 7+8 atomic. |
| A3 | all 5 JS actions | `using: node20` → `node24`. The runner already warns node20 is deprecated. |
| A4 | `commits_since_tag` | Use its own input instead of `env.tag` set by a sibling action. Handle the no-tag case (`git log HEAD`). |

New actions, referenced by nothing until the pilot adopts them:

| # | action | purpose |
|---|---|---|
| A5 | `resolve_base_version` | Releases API → filter → `sort -V \| tail -1` → `base_tag`, `base_version`. Replaces `read_current_version` + `find_current_tag`. Defaults to `0.0.0`. |
| A6 | `check_central_published` | `curl -sfI` the `.pom` on repo1 per artifact; `published=true` only if all exist. |
| A7 | `common_modules_predeploy_release` | Composite: A5 → A4 → `find_pull_requests` → A1 → `update_version` → `generate_changelog`. Writes no files. |

Deprecated but **not deleted** — the other six still reference them at `@main`:
`read_current_version`, `find_current_tag`, `write_updated_version`, `update_changelog`,
`push_version_update`, `push_version_tag`, `common_modules_postdeploy`,
`common_modules_predeploy_properties`. Delete once all seven are migrated.

### B. Pilot repo (`android-common-kotlin`)

**B1 — `build.gradle.kts`.** `version` is consumed in exactly one place —
`kotlin/build.gradle.kts:52`, inside `coordinates(...)`. Nothing in `buildSrc` touches it.
`version.properties` has exactly one reader, `build.gradle.kts:7`.

That `coordinates(...)` call sits inside `afterEvaluate`, which runs at configuration time
on every Gradle invocation, and vanniktech's `coordinates()` takes a `String`, not a
`Provider`. An unconditional hard failure would therefore break `./gradlew test`, `detekt`
and IDE sync. Scope the failure to publish tasks:

```kotlin
val isPublishing = gradle.startParameter.taskNames.any { it.contains("publish", ignoreCase = true) }

version = providers.gradleProperty("releaseVersion").orNull
    ?: if (isPublishing) {
        error("Publishing requires -PreleaseVersion=<x.y.z>. CI supplies this; " +
              "locally, decide the version deliberately.")
    } else {
        "0.0.0-LOCAL"
    }
```

Any publish — CI or a local `publishToMavenLocal` — without an explicit version fails
loudly and can never ship a silently wrong coordinate. `0.0.0-LOCAL` is deliberately not a
plausible release number.

**B2 / B3 — deferred.** `version.properties` and `CHANGELOG.md` stay until the migration
is reviewed and approved. Both go stale immediately: `version.properties` will still read
`0.2.0` while Central moves on, and `CHANGELOG.md` freezes at `v0.2.0` because
`update_changelog` leaves the chain. Add a one-line header to each — *"Not maintained
during release-flow migration; see GitHub Releases"* — and delete both in a separate PR
after review.

Verified 2026-09-15: the `v0.1.0` and `v0.2.0` release bodies match `CHANGELOG.md`
exactly, so deleting the file loses nothing.

**B4 — `release.yml`** (new file; `autodeploy.yml` untouched until cutover). Drops
`ssh-key` and `submodules` (the repo has no `.gitmodules`), adds
`permissions: contents: write`, keeps `fetch-depth: 0` and the `concurrency` group, uses
`publishAndReleaseToMavenCentral -PreleaseVersion=… --no-parallel`, inserts the A6 guard,
and ends with the single atomic record step.

**B5 — `static.yml`.** Render `docs/changelog.html` from the Releases API before
`upload-pages-artifact`. Because a `GITHUB_TOKEN`-created release emits no
`release: published` event, `release.yml` invokes the Pages workflow directly via
`workflow_dispatch` after a successful record.

### C. Testing

`test-scripts.yml` already runs bash and Python tests from `scripts/tests/`. Put the
version-resolution and Central-guard logic in `scripts/` as plain bash so that harness
covers it — semver sort and URL construction are pure functions, testable offline.
Required cases: `2.2.3` / `10.0.0` / `12.1.3` ordering; `0.9.0` / `0.10.0` ordering;
empty release list; draft and prerelease filtering; `check_central_published` true-path
against `com.infinum.android.common:kotlin:0.2.0`, which genuinely exists.

The JS actions have no tests. Add coverage for the `get_pull_request_details` output
shape only; do not expand scope further.

## Rollout

The new flow lands as a **new** workflow file that is `workflow_dispatch`-only at first.
`autodeploy.yml` stays in place (and failing) until the new path has proven itself, so
every phase is reversible and cutover is deliberate.

### Phase 0 — baseline, read-only
Record tags, releases, Central versions and CI state for all seven. Human check that
cannot be automated: confirm `MAVEN_CENTRAL_USER` / `MAVEN_CENTRAL_PW` are Central
**Portal** tokens, not OSSRH ones. Note these are **repo-level** secrets — each repo
holds its own copy, so confirming one says nothing about another. (Established
2026-09-16 while debugging a signing failure: `android-common-view`'s
`DEPLOY_IN_MEMORY_SIGNING_KEY` was malformed and unparseable while every other repo's
worked.)

### Phase 1 — shared-action fixes (live for all 7)
A1, A2, A3, A4.

Pass condition, and a useful canary: re-run a failed autodeploy and confirm the
**predeploy step (step 6) now succeeds** and the failure moves downstream. The expected
downstream failure differs by repo, and both outcomes are a pass:

| repo | before A1 | after A1 |
|---|---|---|
| the two OSSRH repos (`junit`, `ui`) | step 6, `Argument list too long` | step 7 `Deploy`, OSSRH **HTTP 402** |
| `android-common-kotlin` | step 6, `Argument list too long` | step 8 `Commit and push changes`, **`GH013`** |

This proves A1 works across repos without any repo publishing anything — the two OSSRH
repos cannot reach the push at all, and kotlin's deploy stages locally without reaching
Central.

### Phase 2 — new actions, referenced by nothing
A5, A6, A7 plus their bash logic in `scripts/` and tests in `scripts/tests/`.
Blast radius zero. Pass condition: `test-scripts.yml` green including the sort cases.

### Phase 3 — rehearsal on `android-common-projects-test-setup`

This repo is private, has no consumers, carries the richest release history in the org
(16 tags / 15 releases, including patch versions `0.1.1`, `0.1.2`, `0.3.1`, `0.4.1`,
`0.4.2`, `0.7.1`, `0.7.2`, `0.7.3`), is already on vanniktech 0.32.0 / Central Portal, and
its last autodeploy **succeeded** — so it is a working baseline to diff against. Its
default branch is `master`, which additionally proves the new workflow does not hardcode
`main`.

**Deploy is pinned to `publishToMavenLocal`. Real Maven Central is never touched from this
repo.** Only its `android` module publishes, at
`com.infinum.android.common:common-modules-test` — 404 on Central today, so switching it
to `publishAndReleaseToMavenCentral` would publish to public Central for the first time,
permanently. Explicitly rejected.

Because `publishToMavenLocal` cannot realistically fail, the constraint is proven by
deliberate failure injection instead:

| run | deploy step | asserts |
|---|---|---|
| 1 | `publishToMavenLocal` | base resolves to `v0.7.3` from 15 releases; `sort -V` picks it over `v0.7.2` / `v0.1.2`; 0 commits since → no-op, nothing created |
| 2 | `publishToMavenLocal` | merge a labeled PR → bump to `0.8.0`; changelog renders; artifact in `~/.m2` at `0.8.0`; **tag + release created together** |
| 3 | `exit 1` (injected) | **no tag, no release, nothing in `~/.m2`** — the constraint |
| 4 | `publishToMavenLocal` | after the injected failure, base is still `v0.8.0`; retries the same version cleanly |

Run 4 is the redeploy-after-failure behaviour, proven end to end.

`check_central_published` exercises only its `false` path here; the `true` path is covered
in `scripts/tests/`.

Tags and releases left behind (`v0.8.0`, `v0.8.1`…) are kept — they become more test data.

**What this phase cannot prove.** The org ruleset does **not** apply to this repo —
querying it, `Main Branch Protection` (id `8879073`) returns 0 matches. Its only ruleset is
repo-level:

```
"Default branch protection"  source_type: Repository
bypass_actors: [ DeployKey (always), RepositoryRole 5 / admin (always) ]
current_user_can_bypass: "always"
```

Almost certainly because this repo is private while the seven modules are public. `GH013`
cannot reproduce here, which is exactly why its old flow still works. A green run here says
nothing about whether the ruleset problem is solved.

### Phase 4 — pilot build change, no release
B1 only; `version.properties` stays. Normal PR into `android-common-kotlin` (SonarCloud,
Bitrise, Danger apply). Provable offline:

```bash
./gradlew build                                     # 0.0.0-LOCAL, passes
./gradlew publishToMavenLocal                       # fails with the explicit message
./gradlew publishToMavenLocal -PreleaseVersion=9.9.9
ls ~/.m2/repository/com/infinum/android/common/kotlin/9.9.9/
```

### Phase 5 — pilot dry run
Land `release.yml`, dispatch-only, `dry_run` defaulting to true.

| check | expected |
|---|---|
| `resolve_base_version` | `v0.2.0` / `0.2.0` |
| commits since `v0.2.0` | 26 PRs, no `Argument list too long` |
| computed version | `0.3.0` |
| changelog | 26 entries, renders |
| `check_central_published(0.3.0)` | `false` |
| `publishToMavenLocal -PreleaseVersion=0.3.0` | succeeds, correct coordinates |
| tag / release created | **none** |

### Phase 6 — first real release
Dispatch with `dry_run=false` — still manual, so it is deliberate. This is where a stuck
Portal deployment surfaces: deploy fails, nothing is tagged, released or published; a
human drops the deployment and re-runs. On success `v0.3.0` tag and release appear together
from the single API call; confirm on `repo1.maven.org` after propagation.

Expected first version: the 26 backlogged PRs are mostly unlabeled Renovate bumps →
`otherChanges` → minor bump → **0.3.0**, with a 26-entry changelog.

### Phase 7 — cutover
Add the `push` trigger to `release.yml`, delete `autodeploy.yml`. Verify both paths with
real merges: first a PR labeled `skip-release` (proves the skip path creates nothing), then
an ordinary one.

### Phase 8 — Pages changelog
B5, after Phase 6 so there is real release data to render.

### Phase 9 — review gate
Tech lead reviews. B2/B3 (deleting `version.properties` and `CHANGELOG.md`) land as a
separate PR.

### Phase 10 — the two OSSRH repos
Blocked on the OSSRH → Central Portal migration. One repo at a time, Portal migration as
its own reviewed PR per repo, reusing the now-proven shared actions.

## Rollback

- **Phases 1–2:** revert the shared-action commits; the other six return to their prior state.
- **Phase 3 (rehearsal):** revert the changes in `android-common-projects-test-setup` and
  leave its tags and releases in place. Nothing outside that repo is affected.
- **Phases 4–5 (pilot, pre-release):** revert the pilot PR. **Set `version.properties` to
  the real current version first** — it will have drifted.
- **Phase 6 onward:** a published Central version cannot be withdrawn. Rollback means
  keeping the tag and release and resuming the old flow from that version, with
  `version.properties` corrected to match.

## Decisions taken

| decision | choice | why |
|---|---|---|
| Approach | Tag-derived versioning, no writes to the default branch | Removes the problem rather than routing around it; needs no org-owner action and no bot approving a bot |
| Version source | GitHub Releases, semver-sorted | A stray tag cannot shift the base; drafts and prereleases filtered for free; same source feeds the Pages changelog |
| Tag + release | Single `createRelease` call with `target_commitish` | Genuinely atomic; removes the tag-without-release state |
| Deploy gate | `publishAndReleaseToMavenCentral` | The current task skips validation and exits 0 without publishing |
| Ordering | Deploy, then record | A failed deploy must leave no tag, so the next release retries |
| CHANGELOG.md | Generated onto the Pages docs from the Releases API | Keeps a browsable changelog with zero writes to the default branch |
| Local version | Hard fail for publish tasks, `0.0.0-LOCAL` otherwise | Cannot silently ship a wrong coordinate; does not break IDE sync |
| Pilot | `android-common-kotlin` | Only repo already on Central Portal; `junit` and five others are stuck on dead OSSRH |
| Rehearsal | `android-common-projects-test-setup`, local publish only | Best test data, zero consequences; never publishes to real Central |
| Portal deployments | Never dropped automatically | Irreversible; always a human decision |
| `version.properties` / `CHANGELOG.md` | Deleted only after review | Keeps rollback cheap during the trial |

## Open questions

- **Release cadence.** Every merge to the default branch currently cuts a release, so each
  Renovate bump ships a minor version. Unchanged by this work; worth revisiting separately.
- **Org-wide rollout of the OSSRH migration.** Sequencing and ownership for the remaining
  two repos, `junit` and `ui`.
