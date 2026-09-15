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
