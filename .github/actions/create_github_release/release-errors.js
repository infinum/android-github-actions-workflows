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
