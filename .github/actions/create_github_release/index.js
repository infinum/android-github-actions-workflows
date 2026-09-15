const core = require('@actions/core');
const github = require('@actions/github');
const { context } = require('@actions/github');
const { isAlreadyExistsError } = require('./release-errors');

async function run() {
  try {
    const newVersion = core.getInput('updated_version');
    const ghToken = core.getInput('github_token');
    const changelog = core.getInput('changelog');
    const targetCommitish = core.getInput('target_commitish') || process.env.GITHUB_SHA;

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
