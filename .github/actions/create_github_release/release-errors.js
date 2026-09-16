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

// True only when the caller explicitly supplied a target commit. See
// resolveDuplicateOutcome below for why this distinction exists.
function shouldUseStrictVerification(explicitTargetCommitish) {
  return Boolean(explicitTargetCommitish);
}

// Resolves a tag name to the commit SHA it actually points at. Handles both
// lightweight tags (ref points straight at a commit) and annotated tags
// (ref points at a tag object, which itself points at a commit). octokit is
// injected so callers (and tests) can supply a stub — the same seam
// resolveDuplicateOutcome uses for its resolveActualSha parameter below.
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

// Compares the commit a duplicate tag/release actually points at against
// the commit that was expected, and reports whether they match. Pure
// comparison only — whether this check should even run is
// resolveDuplicateOutcome's decision, not this function's.
function checkCommitMatch({ tag, expectedSha, actualSha }) {
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
// network in lenient mode. This is the sole owner of the
// strict-versus-lenient policy for the whole module.
//
// createRelease silently ignores target_commitish when the tag already
// exists, so a duplicate 422 alone does not prove the existing release
// points at the commit that was actually published to Maven Central. In
// strict mode (target_commitish explicitly supplied by the caller) the
// caller's intent is unambiguous, so we require the existing tag's commit
// to match exactly. In lenient mode (legacy callers that never pass
// target_commitish, relying on the GITHUB_SHA fallback) the tag is always
// created by an earlier step in their pipeline at a commit that is never
// GITHUB_SHA by design, so we keep the original tolerant behaviour rather
// than break six repos that never asked for the strict check — the early
// return below is what guarantees that, and it must never touch the
// network or call resolveActualSha in lenient mode: the lookup can fail
// for reasons unrelated to commit verification (deleted tag ref, transient
// API error, missing permissions), and those six legacy callers must keep
// converging on a duplicate 422 regardless.
//
// resolveActualSha is a caller-supplied async lookup (normally "read the
// tag ref, dereference it to a commit"), only ever invoked in strict mode.
// A lookup failure there is reported as a distinct, loud failure ("could
// not verify") rather than folded into the "wrong commit" message
// checkCommitMatch produces — an operator needs to tell "we don't know
// what this tag points at" apart from "we know, and it's wrong".
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

  return checkCommitMatch({ tag, expectedSha, actualSha });
}

module.exports = {
  isAlreadyExistsError,
  shouldUseStrictVerification,
  resolveTagCommitSha,
  checkCommitMatch,
  resolveDuplicateOutcome
};
