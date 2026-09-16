const test = require('node:test');
const assert = require('node:assert');
const {
  isAlreadyExistsError,
  shouldUseStrictVerification,
  resolveTagCommitSha,
  checkCommitMatch,
  resolveDuplicateOutcome
} = require('../release-errors');

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

test('checkCommitMatch: passes when SHAs match', () => {
  const result = checkCommitMatch({ tag: 'v1.2.3', expectedSha: 'abc123', actualSha: 'abc123' });
  assert.strictEqual(result.ok, true);
});

test('checkCommitMatch: fails when SHAs differ, naming tag and both SHAs', () => {
  const result = checkCommitMatch({ tag: 'v1.2.3', expectedSha: 'abc123', actualSha: 'def456' });
  assert.strictEqual(result.ok, false);
  assert.match(result.message, /v1\.2\.3/);
  assert.match(result.message, /abc123/);
  assert.match(result.message, /def456/);
});

test('checkCommitMatch: fails when a SHA is missing or undefined', () => {
  assert.strictEqual(
    checkCommitMatch({ tag: 'v1.2.3', expectedSha: undefined, actualSha: 'def456' }).ok,
    false
  );
  assert.strictEqual(
    checkCommitMatch({ tag: 'v1.2.3', expectedSha: 'abc123', actualSha: undefined }).ok,
    false
  );
  assert.strictEqual(
    checkCommitMatch({ tag: 'v1.2.3', expectedSha: undefined, actualSha: undefined }).ok,
    false
  );
});

test('resolveDuplicateOutcome: lenient mode succeeds without ever calling the resolver', async () => {
  let callCount = 0;
  const resolveActualSha = async () => {
    callCount += 1;
    return 'def456';
  };

  const result = await resolveDuplicateOutcome({
    tag: 'v1.2.3',
    expectedSha: 'abc123',
    strict: false,
    resolveActualSha
  });

  assert.strictEqual(result.ok, true);
  assert.strictEqual(callCount, 0, 'the tag lookup must not be attempted in lenient mode');
});

test('resolveDuplicateOutcome: strict mode calls the resolver and succeeds on a match', async () => {
  let callCount = 0;
  const resolveActualSha = async () => {
    callCount += 1;
    return 'abc123';
  };

  const result = await resolveDuplicateOutcome({
    tag: 'v1.2.3',
    expectedSha: 'abc123',
    strict: true,
    resolveActualSha
  });

  assert.strictEqual(result.ok, true);
  assert.strictEqual(callCount, 1);
});

test('resolveDuplicateOutcome: strict mode fails on a resolved mismatch, via checkCommitMatch', async () => {
  const result = await resolveDuplicateOutcome({
    tag: 'v1.2.3',
    expectedSha: 'abc123',
    strict: true,
    resolveActualSha: async () => 'def456'
  });

  assert.strictEqual(result.ok, false);
  assert.match(result.message, /not the expected commit/);
});

test('resolveDuplicateOutcome: strict mode reports a distinct, loud failure when the lookup itself throws', async () => {
  const result = await resolveDuplicateOutcome({
    tag: 'v1.2.3',
    expectedSha: 'abc123',
    strict: true,
    resolveActualSha: async () => {
      throw new Error('Not Found');
    }
  });

  assert.strictEqual(result.ok, false);
  assert.match(result.message, /could not verify/i);
  assert.match(result.message, /v1\.2\.3/);
  assert.match(result.message, /Not Found/);
  // Must be distinguishable from the "wrong commit" message a resolved
  // mismatch produces — an operator needs to tell "unknown" from "wrong".
  assert.doesNotMatch(result.message, /not the expected commit/);
});

test('shouldUseStrictVerification: false when target_commitish is absent', () => {
  assert.strictEqual(shouldUseStrictVerification(undefined), false);
});

test('shouldUseStrictVerification: false when target_commitish is empty', () => {
  assert.strictEqual(shouldUseStrictVerification(''), false);
});

test('shouldUseStrictVerification: true when target_commitish is a supplied SHA', () => {
  assert.strictEqual(shouldUseStrictVerification('abc123'), true);
});

test('resolveTagCommitSha: returns the commit SHA directly for a lightweight tag', async () => {
  const octokit = {
    rest: {
      git: {
        getRef: async ({ owner, repo, ref }) => {
          assert.strictEqual(owner, 'infinum');
          assert.strictEqual(repo, 'demo');
          assert.strictEqual(ref, 'tags/v1.2.3');
          return { data: { object: { sha: 'commit-sha', type: 'commit' } } };
        },
        getTag: async () => {
          throw new Error('getTag must not be called for a lightweight tag');
        }
      }
    }
  };

  const sha = await resolveTagCommitSha(octokit, 'infinum', 'demo', 'v1.2.3');
  assert.strictEqual(sha, 'commit-sha');
});

test('resolveTagCommitSha: dereferences an annotated tag to its underlying commit SHA', async () => {
  const octokit = {
    rest: {
      git: {
        getRef: async () => ({ data: { object: { sha: 'tag-object-sha', type: 'tag' } } }),
        getTag: async ({ tag_sha }) => {
          assert.strictEqual(tag_sha, 'tag-object-sha');
          return { data: { object: { sha: 'underlying-commit-sha', type: 'commit' } } };
        }
      }
    }
  };

  const sha = await resolveTagCommitSha(octokit, 'infinum', 'demo', 'v1.2.3');
  assert.strictEqual(sha, 'underlying-commit-sha');
});

test('resolveTagCommitSha: dereferences a chain of nested tag objects to the final commit SHA', async () => {
  const octokit = {
    rest: {
      git: {
        getRef: async () => ({ data: { object: { sha: 'tag-1', type: 'tag' } } }),
        getTag: async ({ tag_sha }) => {
          if (tag_sha === 'tag-1') {
            return { data: { object: { sha: 'tag-2', type: 'tag' } } };
          }
          if (tag_sha === 'tag-2') {
            return { data: { object: { sha: 'final-commit-sha', type: 'commit' } } };
          }
          throw new Error(`unexpected tag_sha ${tag_sha}`);
        }
      }
    }
  };

  const sha = await resolveTagCommitSha(octokit, 'infinum', 'demo', 'v1.2.3');
  assert.strictEqual(sha, 'final-commit-sha');
});
