const core = require('@actions/core');
const github = require('@actions/github');
const { context } = require('@actions/github');
const { toPrData, deriveBumpFlags, hasSkipRelease } = require('./pr-data');

async function run() {
  try {
    const prNumbers = core.getInput('pr_numbers');
    if (!prNumbers) {
      core.info('No pull request numbers provided.');
      return;
    }

    const token = core.getInput('github_token');
    const octokit = github.getOctokit(token);
    const prNumberList = prNumbers.split(' ').filter(Boolean);

    const mostRecentPr = prNumberList[prNumberList.length - 1];
    const { data: mostRecentPrDetail } = await octokit.rest.pulls.get({
      owner: context.repo.owner,
      repo: context.repo.repo,
      pull_number: mostRecentPr
    });

    if (hasSkipRelease(mostRecentPrDetail.labels.map(label => label.name))) {
      core.info('Most recent PR has skip-release label. Skipping the release.');
      core.exportVariable('pr_details', '[]');
      core.setOutput('pr_details', '[]');
      return;
    }

    const prDetails = [];
    for (const pr of prNumberList) {
      const { data: prDetail } = await octokit.rest.pulls.get({
        owner: context.repo.owner,
        repo: context.repo.repo,
        pull_number: pr
      });
      prDetails.push(toPrData(prDetail));
    }

    const { breakingChange, newFeature, bugfix } = deriveBumpFlags(prDetails);
    const serialized = JSON.stringify(prDetails);

    core.exportVariable('pr_details', serialized);
    core.exportVariable('breaking_change', breakingChange);
    core.exportVariable('new_feature', newFeature);
    core.exportVariable('bugfix', bugfix);

    core.setOutput('pr_details', serialized);
    core.setOutput('is_breaking_change', breakingChange);
    core.setOutput('is_new_feature', newFeature);
    core.setOutput('is_bugfix', bugfix);

    core.info(`pr_details bytes=${serialized.length} count=${prDetails.length}`);
    core.info(`breaking_change=${breakingChange}`);
    core.info(`new_feature=${newFeature}`);
    core.info(`bugfix=${bugfix}`);
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
