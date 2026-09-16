// Pure helpers for shaping pull request API responses into changelog data.
//
// The PR body is deliberately NOT carried. generate_changelog reads only
// title, author, number and labels, and passing bodies between steps
// overflows ARG_MAX once a release backlog builds up.

const BREAKING_CHANGE = 'breaking-change';
const NEW_FEATURE = 'new-feature';
const BUGFIX = 'bugfix';
const SKIP_RELEASE = 'skip-release';

function toPrData(prDetail) {
  return {
    title: prDetail.title,
    labels: prDetail.labels.map(label => label.name),
    number: prDetail.number,
    author: prDetail.user.login
  };
}

function deriveBumpFlags(prDataList) {
  const has = label => prDataList.some(pr => pr.labels.includes(label));
  return {
    breakingChange: has(BREAKING_CHANGE),
    newFeature: has(NEW_FEATURE),
    bugfix: has(BUGFIX)
  };
}

function hasSkipRelease(labels) {
  return labels.includes(SKIP_RELEASE);
}

module.exports = { toPrData, deriveBumpFlags, hasSkipRelease };
