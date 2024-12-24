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

    // Filter out PRs with the label "skip-changelog"
    const filteredPrDetails = prDetails.filter(pr => !pr.labels.includes('skip-changelog'));
    const breakingChangePrs = filteredPrDetails.filter(pr => pr.labels.includes('breaking-change'));
    const newFeaturePrs = filteredPrDetails.filter(pr => pr.labels.includes('new-feature'));
    const bugfixPrs = filteredPrDetails.filter(pr => pr.labels.includes('bugfix'));

    // Compute otherChangesPrs based on the filtered PRs
    const otherChangesPrs = filteredPrDetails.filter(pr =>
      !breakingChangePrs.includes(pr) &&
      !newFeaturePrs.includes(pr) &&
      !bugfixPrs.includes(pr)
    );

    let changelog = '';
    const breakingChanges = breakingChangePrs.map(pr => `- ${pr.title} by @${pr.author} in #${pr.number}`).join('\n');
    const newFeatures = newFeaturePrs.map(pr => `- ${pr.title} by @${pr.author} in #${pr.number}`).join('\n');
    const bugfixes = bugfixPrs.map(pr => `- ${pr.title} by @${pr.author} in #${pr.number}`).join('\n');
    const otherChanges = otherChangesPrs.map(pr => `- ${pr.title} by @${pr.author} in #${pr.number}`).join('\n');

    if (breakingChanges) {
      changelog += '### Breaking Changes\n' + breakingChanges + '\n\n';
    }
    if (newFeatures) {
      changelog += '### New Features\n' + newFeatures + '\n\n';
    }
    if (bugfixes) {
      changelog += '### Bug Fixes\n' + bugfixes + '\n\n';
    }
    if (otherChanges && !breakingChanges && !newFeatures && !bugfixes) {
      changelog += '### Changes\n' + otherChanges + '\n\n';
    } else if (otherChanges) {
      changelog += '### Other Changes\n' + otherChanges + '\n\n';
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