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

// Strict verification only applies when the caller explicitly asked for a
// specific commit. Legacy callers never pass target_commitish: their tag is
// created by an earlier step (push_version_tag) at a commit that is never
// GITHUB_SHA by design, so a strict check would fail them every time. Keep
// them on today's lenient behaviour.
function shouldUseStrictVerification(explicitTargetCommitish) {
  return Boolean(explicitTargetCommitish);
}

// Resolves a tag name to the commit SHA it actually points at. Handles both
// lightweight tags (ref points straight at a commit) and annotated tags
// (ref points at a tag object, which itself points at a commit). octokit is
// injected so callers (and tests) can supply a stub, the same seam used by
// resolveDuplicateOutcome's resolveActualSha parameter below.
async function resolveTagCommitSha(octokit, owner, repo, tag) {
  const { data: ref } = await octokit.rest.git.getRef({ owner, repo, ref: `tags/${tag}` });
  let sha = ref.object.sha;
  let type = ref.object.type;

  while (type === 'tag') {
    const { data: tagObject } = await octokit.rest.git.getTag({ owner, repo, tag_sha: sha });
    sha = tagObject.object.sha;
    type = tagObject.object.type;
  }

  return sha;
}

// Decides whether a pre-existing tag/release is safe to treat as success.
//
// createRelease silently ignores target_commitish when the tag already
// exists, so a duplicate 422 alone does not prove the existing release
// points at the commit that was actually published to Maven Central. In
// strict mode (target_commitish explicitly supplied by the caller) the
// caller's intent is unambiguous, so we require the existing tag's
// commit to match exactly. In lenient mode (legacy callers that never
// pass target_commitish, relying on the GITHUB_SHA fallback) the tag is
// always created by an earlier step in their pipeline at a commit that
// is never GITHUB_SHA by design, so we keep the original tolerant
// behaviour rather than break six repos that never asked for the strict
// check.
function checkCommitMatch({ tag, expectedSha, actualSha, strict }) {
  if (!strict) {
    return { ok: true };
  }
  if (!expectedSha || !actualSha) {
    return {
      ok: false,
      message: `Release ${tag} already exists but its commit could not be verified ` +
        `(expected ${expectedSha || '<unknown>'}, actual ${actualSha || '<unknown>'}).`
    };
  }
  if (expectedSha !== actualSha) {
    return {
      ok: false,
      message: `Release ${tag} already exists but points at commit ${actualSha}, ` +
        `not the expected commit ${expectedSha}.`
    };
  }
  return { ok: true };
}

// Decides what to do about a duplicate 422, without ever touching the
// network in lenient mode.
//
// resolveActualSha is a caller-supplied async lookup (normally "read the
// tag ref, dereference it to a commit"). It must only be invoked when
// strict is true: in lenient mode checkCommitMatch always returns
// ok:true regardless of actualSha, so calling the lookup there would be
// pure waste that can also fail for reasons unrelated to commit
// verification (deleted tag ref, transient API error, missing
// permissions) — and the six legacy callers, who never asked for strict
// verification, must keep converging on a duplicate 422 even when that
// lookup would have failed.
//
// In strict mode, a lookup failure is reported as a distinct, loud
// failure ("could not verify") rather than folded into the "wrong
// commit" message checkCommitMatch produces — an operator needs to tell
// "we don't know what this tag points at" apart from "we know, and it's
// wrong".
async function resolveDuplicateOutcome({ tag, expectedSha, strict, resolveActualSha }) {
  if (!strict) {
    return { ok: true };
  }

  let actualSha;
  try {
    actualSha = await resolveActualSha();
  } catch (error) {
    return {
      ok: false,
      message: `Could not verify which commit tag ${tag} points at (release already exists): ${error.message}`
    };
  }

  return checkCommitMatch({ tag, expectedSha, actualSha, strict });
}

module.exports = {
  isAlreadyExistsError,
  shouldUseStrictVerification,
  resolveTagCommitSha,
  checkCommitMatch,
  resolveDuplicateOutcome
};
