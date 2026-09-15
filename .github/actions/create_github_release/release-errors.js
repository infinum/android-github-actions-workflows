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

module.exports = { isAlreadyExistsError, checkCommitMatch };
