const test = require('node:test');
const assert = require('node:assert');
const { isAlreadyExistsError, checkCommitMatch, resolveDuplicateOutcome } = require('../release-errors');

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

test('checkCommitMatch: strict mode passes when SHAs match', () => {
  const result = checkCommitMatch({ tag: 'v1.2.3', expectedSha: 'abc123', actualSha: 'abc123', strict: true });
  assert.strictEqual(result.ok, true);
});

test('checkCommitMatch: strict mode fails when SHAs differ, naming tag and both SHAs', () => {
  const result = checkCommitMatch({ tag: 'v1.2.3', expectedSha: 'abc123', actualSha: 'def456', strict: true });
  assert.strictEqual(result.ok, false);
  assert.match(result.message, /v1\.2\.3/);
  assert.match(result.message, /abc123/);
  assert.match(result.message, /def456/);
});

test('checkCommitMatch: lenient mode never fails, even when SHAs differ', () => {
  const result = checkCommitMatch({ tag: 'v1.2.3', expectedSha: 'abc123', actualSha: 'def456', strict: false });
  assert.strictEqual(result.ok, true);
});

test('checkCommitMatch: strict mode fails when a SHA is missing or undefined', () => {
  assert.strictEqual(
    checkCommitMatch({ tag: 'v1.2.3', expectedSha: undefined, actualSha: 'def456', strict: true }).ok,
    false
  );
  assert.strictEqual(
    checkCommitMatch({ tag: 'v1.2.3', expectedSha: 'abc123', actualSha: undefined, strict: true }).ok,
    false
  );
  assert.strictEqual(
    checkCommitMatch({ tag: 'v1.2.3', expectedSha: undefined, actualSha: undefined, strict: true }).ok,
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
