const test = require('node:test');
const assert = require('node:assert');
const { shouldUseStrictVerification, resolveTagCommitSha } = require('../index');

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
