const core = require('@actions/core');
const github = require('@actions/github');
const exec = require('@actions/exec');
const { context } = require('@actions/github');

async function run() {
  try {
    const commits = core.getInput('commits');
    if (!commits) {
      core.info('No commits provided.');
      return;
    }

    const token = core.getInput('github_token');
    const octokit = github.getOctokit(token, {
      log: console,
    });

    let prDetails = [];
    const commitList = commits.split(' ');

    const { data: rateLimit } = await octokit.rest.rateLimit.get();
    core.info(`Rate limit remaining: ${rateLimit}`);

    for (const commit of commitList) {
      core.info(`Processing ${commit}...`);
      const { data: prs } = await octokit.rest.search.issuesAndPullRequests({
        q: `${commit} repo:${context.repo.owner}/${context.repo.repo} is:pr is:merged`,
      });

      prs.items.forEach(pr => {
        prDetails.push({ number: pr.number, mergedAt: pr.pull_request.merged_at });
      });
    }

    prDetails.sort((a, b) => new Date(a.mergedAt) - new Date(b.mergedAt));
    const prNumbers = [...new Set(prDetails.map(pr => pr.number))].join(' ');
    
    if (!prNumbers) {
      core.info(`Pull requests with commits ${commits} not found! Skipping the release.`);
      core.exportVariable('pr_numbers', '');
    } else {
      core.exportVariable('pr_numbers', prNumbers);
    }

    core.info(`pr_numbers=${prNumbers}`);
    core.setOutput('pr_numbers', prNumbers);
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
