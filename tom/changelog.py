import re
import os
import requests
import subprocess
import datetime
import hashlib
import urllib.request
import logging as log
from tom.git import GitRepo


class ChangelogException(Exception):
    """Base class for all exceptions in this file"""

    pass


class ChangelogParsingException(ChangelogException):
    """Exception that is risen if old version can't be found in existing changelog file"""

    pass


class ChangelogGenerator:
    """Class responsible for generating changelogs.
    Currently it generates changelog only for CFEngine, as described at
    https://github.com/mendersoftware/infra/blob/master/files/buildcache/release-scripts/RELEASE_PROCESS.org#generate-changelogs
    """

    repos_root = ".."
    changelog_filenames = {
        "core": "ChangeLog",
        "enterprise": "ChangeLog.Enterprise",
        "masterfiles": "CHANGELOG.md",
    }

    def __init__(self, github, slack, dispatcher, username):
        self.github = github
        self.slack = slack
        self.username = username
        dispatcher.register_command(
            keyword="changelogs",
            callback=lambda branch: self.run(branch),
            parameter_name="branch",
            short_help="Generate changelogs",
            long_help="Generate changelogs and create PR with them",
        )

    def split_changelog_into_parts(self, changelog_filename, repo):
        """Splits changelog into header, last version, and everything else
        Returns tuple of three elements:
        - header (part which goes before changelog)
        - last version
        - rest of changelog, including last version
        """
        changelog_file = repo.get_file(changelog_filename)
        changelog_lines = changelog_file.splitlines()
        for i in range(5):
            # look for line having proper version
            m = re.match("^([0-9]+\\.[0-9]+\\.[0-9]+):$", changelog_lines[i])
            if m:
                return (
                    "\n".join(changelog_lines[:i]),
                    m.group(1),
                    "\n".join(changelog_lines[i:]),
                )
        raise ChangelogParsingException(
            (
                "Failed to find version in changelog "
                + "file, top 5 lines are: {}. Remember that version should be "
                + "three groups of numbers separated by dots and ending with "
                + 'colon, for example "3.12.0:"'
            ).format(changelog_lines[:5])
        )

    @staticmethod
    def get_next_version(old_version, branch):
        version_parts = old_version.split(".")
        if branch == "master":
            try:
                # increase minor version and set patch version to 0,
                # i.e. 3.10.2 -> 3.11.0
                version_parts[1] = str(int(version_parts[1]) + 1)
                version_parts[2] = "0"
            except:
                # ???
                raise
        else:
            # TODO: branch='3.18.0-x' vs branch='3.18.x'
            if branch == "{}.{}.x".format(version_parts[0], version_parts[1]):
                # we already had version corresponding to a branch name,
                # i.e. version 3.10.2 on a branch 3.10.x
                # so increase patch version
                # i.e. 3.10.2 -> 3.10.3
                version_parts[2] = str(int(version_parts[2]) + 1)
            else:
                # this is a first version on this branch
                # so set it to [branch_name].0
                branch_name_parts = branch.split(".")
                version_parts = branch_name_parts[0:2] + ["0"]
        return ".".join(version_parts)

    def get_changelog_for(self, name, arg, old_version, branch):
        olddir = os.getcwd()
        try:
            os.chdir(os.path.join(self.repos_root, name))
            cmd = [
                "../core/misc/changelog-generator/changelog-generator",
                arg,
                "{}...{}".format(old_version, branch),
            ]
            log.debug("running command: {}".format(" ".join(cmd)))
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, universal_newlines=True, check=True
            )
        finally:
            os.chdir(olddir)
        return proc.stdout

    def generate_changelog_in_repo(self, branch, repo):
        name = repo.repo_name
        changelog_filename = self.changelog_filenames.get(name)
        if not changelog_filename:
            # no need to generate changelog in _this_ repo
            return False

        # find old and new versions
        (header, old_version, old_changelog) = self.split_changelog_into_parts(
            changelog_filename, repo
        )
        if header != "":
            header += "\n"
        new_version = self.get_next_version(old_version, branch)
        log.debug("next version: {} => {}".format(old_version, new_version))

        # checkout new branch
        timestamp = re.sub("[^0-9-]", "_", str(datetime.datetime.today()))
        new_branchname = "{}-changelog-{}".format(new_version, timestamp)
        repo.checkout(new_branchname, new=True)

        if name != "enterprise":
            # generate changelog only for this repo
            new_changelog = self.get_changelog_for(name, "--repo", old_version, branch)
            changelog_contents = (
                header
                + new_version
                + ":\n"
                + new_changelog
                + "\n"
                + old_changelog
                + "\n"
            )
        else:
            # generate changelog for all enterprise repos plus buildscipts repo
            changelog_enterprise = self.get_changelog_for(
                name, "--enterprise", old_version, branch
            )
            changelog_buildscripts = self.get_changelog_for(
                "buildscripts", "--repo", old_version, branch
            )
            changelog_contents = (
                new_version
                + ":\n"
                + changelog_enterprise
                + "\n"
                + "        Packaging changes:\n"
                + changelog_buildscripts
                + "\n"
                + old_changelog
                + "\n"
            )

        # push new changelog to repo
        repo.put_file(changelog_filename, changelog_contents)
        repo.commit("Added changelog for " + new_version)
        repo.push(new_branchname)

        # create PR
        pr_text = self.github.create_pr(
            "cfengine/" + name,
            branch,
            self.username,
            new_branchname,
            "Changelog for " + branch,
            "",
        )
        return pr_text

    def run(self, branch):
        """Generate changelogs on a branch, creating PR in the end"""
        self.slack.reply("Generating changelogs on " + branch)
        repo_names = [
            "core",
            "masterfiles",
            "nova",
            "mission-portal",
            "buildscripts",
            "enterprise",
        ]
        # checkout all repos to the required branch
        repos = (
            GitRepo(
                dirname=os.path.join(self.repos_root, name),
                repo_name=name,
                upstream_name="cfengine",
                my_name=self.username,
                checkout_branch=branch,
            )
            for name in repo_names
        )
        # generate changelogs
        prs = (self.generate_changelog_in_repo(branch, repo) for repo in repos)
        # currently prs has False elements corresponding to repos which don't
        # have changelogs. Let's filter them out
        prs = (x for x in prs if x)
        self.slack.reply("Changelog PRs:\n{}".format("\n".join(prs)), True)
