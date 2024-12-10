const core = require('@actions/core');
const github = require('@actions/github');
const { context } = require('@actions/github');

async function run() {
  try {
    const newVersion = core.getInput('updated_version');
    const ghToken = core.getInput('github_token');
    const changelog = core.getInput('changelog');

    const octokit = github.getOctokit(ghToken);

    const releaseResponse = await octokit.repos.createRelease({
      owner: context.repo.owner,
      repo: context.repo.repo,
      tag_name: `v${newVersion}`,
      name: `v${newVersion}`,
      body: changelog
    });

    core.info(`GitHub release v${newVersion} created successfully: ${releaseResponse.data.html_url}`);
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
