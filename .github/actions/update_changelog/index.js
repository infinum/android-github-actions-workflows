const core = require('@actions/core');
const fs = require('fs');

async function run() {
  try {
    const newVersion = core.getInput('updated_version');
    const changelog = core.getInput('changelog');
    const changelogFilename = core.getInput('changelog_filename');
    const currentChangelog = fs.readFileSync(changelogFilename, 'utf8');

    const updatedChangelog = `## v${newVersion}\n\n${changelog}\n\n${currentChangelog}`;
    fs.writeFileSync(changelogFilename, updatedChangelog);

    core.info(`${changelogFilename} updated successfully.`);
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
