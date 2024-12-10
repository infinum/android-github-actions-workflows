const core = require('@actions/core');
const fs = require('fs');
const { context } = require('@actions/github');

async function run() {
  try {
    const prDetails = JSON.parse(core.getInput('pr_details'));
    const currentVersion = core.getInput('current_version');
    const newVersion = core.getInput('updated_version');
    const changelogFilename = core.getInput('changelog_filename');

    if (!prDetails || prDetails.length === 0) {
      core.info('No PR details provided. Skipping changelog generation.');
      return;
    }

    let changelog = '';
    const breakingChanges = prDetails.filter(pr => pr.labels.includes('breaking-change'))
      .map(pr => `- ${pr.title} by @${pr.author} in #${pr.number}`).join('\n');
    const newFeatures = prDetails.filter(pr => pr.labels.includes('new-feature'))
      .map(pr => `- ${pr.title} by @${pr.author} in #${pr.number}`).join('\n');
    const bugfixes = prDetails.filter(pr => pr.labels.includes('bugfix'))
      .map(pr => `- ${pr.title} by @${pr.author} in #${pr.number}`).join('\n');

    if (breakingChanges) {
      changelog += '### Breaking Changes\n' + breakingChanges + '\n\n';
    }
    if (newFeatures) {
      changelog += '### New Features\n' + newFeatures + '\n\n';
    }
    if (bugfixes) {
      changelog += '### Bug Fixes\n' + bugfixes + '\n\n';
    }

    changelog += `\n\n**Full Changelog**: [v${currentVersion}...v${newVersion}](https://github.com/${context.repo.owner}/${context.repo.repo}/compare/v${currentVersion}...v${newVersion})\n`;

    core.info(changelog);
    fs.writeFileSync(changelogFilename, changelog);

    core.setOutput('changelog_filename', changelogFilename);
    core.setOutput('changelog', changelog);
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();