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
