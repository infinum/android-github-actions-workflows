const core = require('@actions/core');
const github = require('@actions/github');
const { context } = require('@actions/github');

async function run() {
  try {
    const prNumbers = core.getInput('pr_numbers');
    if (!prNumbers) {
      core.info('No pull request numbers provided.');
      return;
    }

    const token = core.getInput('github_token');
    const octokit = github.getOcktokit(token);

    let prDetails = [];
    let breakingChange = false;
    let newFeature = false;
    let bugfix = false;

    const prNumberList = prNumbers.split(' ');

    // Get the most recent PR
    const mostRecentPr = prNumberList[prNumberList.length - 1];
    const { data: mostRecentPrDetail } = await octokit.rest.pulls.get({
      owner: context.repo.owner,
      repo: context.repo.repo,
      pull_number: mostRecentPr
    });

    const mostRecentLabels = mostRecentPrDetail.labels.map(label => label.name);

    // Check if the most recent PR has the skip_release label
    if (mostRecentLabels.includes('skip-release')) {
      core.info('Most recent PR has skip-release label. Skipping the release.');
      core.exportVariable('pr_details', '[]');
      return;
    }

    // Process all PRs
    for (const pr of prNumberList) {
      const { data: prDetail } = await octokit.rest.pulls.get({
        owner: context.repo.owner,
        repo: context.repo.repo,
        pull_number: pr
      });

      const prData = {
        title: prDetail.title,
        body: prDetail.body,
        labels: prDetail.labels.map(label => label.name),
        number: prDetail.number,
        author: prDetail.user.login
      };

      prDetails.push(prData);

      const labels = prData.labels;
      if (labels.includes('breaking-change')) {
        breakingChange = true;
      }
      if (labels.includes('new-feature')) {
        newFeature = true;
      }
      if (labels.includes('bugfix')) {
        bugfix = true;
      }
    }

    core.exportVariable('pr_details', JSON.stringify(prDetails));
    core.exportVariable('breaking_change', breakingChange);
    core.exportVariable('new_feature', newFeature);
    core.exportVariable('bugfix', bugfix);

    core.setOutput('pr_details', JSON.stringify(prDetails));
    core.setOutput('is_breaking_change', breakingChange);
    core.setOutput('is_new_feature', newFeature);
    core.setOutput('is_bugfix', bugfix);

    core.info(`pr_details=${JSON.stringify(prDetails)}`);
    core.info(`breaking_change=${breakingChange}`);
    core.info(`new_feature=${newFeature}`);
    core.info(`bugfix=${bugfix}`);
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
