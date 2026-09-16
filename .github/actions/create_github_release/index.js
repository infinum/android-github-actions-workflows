const core = require('@actions/core');
const github = require('@actions/github');
const { context } = require('@actions/github');
const {
  isAlreadyExistsError,
  shouldUseStrictVerification,
  resolveTagCommitSha,
  resolveDuplicateOutcome
} = require('./release-errors');

async function run() {
  try {
    const newVersion = core.getInput('updated_version');
    const ghToken = core.getInput('github_token');
    const changelog = core.getInput('changelog');
    const explicitTargetCommitish = core.getInput('target_commitish');
    const targetCommitish = explicitTargetCommitish || process.env.GITHUB_SHA;
    const strict = shouldUseStrictVerification(explicitTargetCommitish);

    if (!targetCommitish) {
      core.setFailed('No target_commitish supplied and GITHUB_SHA is unset.');
      return;
    }

    const octokit = github.getOctokit(ghToken);
    const tag = `v${newVersion}`;

    try {
      const releaseResponse = await octokit.rest.repos.createRelease({
        owner: context.repo.owner,
        repo: context.repo.repo,
        tag_name: tag,
        target_commitish: targetCommitish,
        name: tag,
        body: changelog
      });
      core.info(`Created tag ${tag} at ${targetCommitish} and release ${releaseResponse.data.html_url}`);
      core.setOutput('release_url', releaseResponse.data.html_url);
    } catch (error) {
      if (isAlreadyExistsError(error)) {
        // createRelease silently ignores target_commitish once the tag
        // already exists, so a 422 alone does not prove the existing
        // release points at the commit we meant to publish. In strict
        // mode, resolve what the tag actually points at and let
        // resolveDuplicateOutcome decide; in lenient mode this never
        // touches the network — see resolveDuplicateOutcome's comment.
        const result = await resolveDuplicateOutcome({
          tag,
          expectedSha: targetCommitish,
          strict,
          resolveActualSha: () => resolveTagCommitSha(octokit, context.repo.owner, context.repo.repo, tag)
        });

        if (!result.ok) {
          core.setFailed(result.message);
          return;
        }

        core.info(`Release ${tag} already exists; treating as success.`);
        core.setOutput('release_url', '');
        return;
      }
      throw error;
    }
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
