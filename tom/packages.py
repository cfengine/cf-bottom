import re
import json
import requests
import collections
import datetime
from tom.git import GitRepo


class PackageMapperException(Exception):
    """Base class for all exceptions in this file"""

    pass


class RepoFileNotFoundException(PackageMapperException):
    """Exception that is risen if a file was not found in repo"""

    pass


class URLDownloadFailureException(PackageMapperException):
    """Exception that is risen if a file was not downloaded"""

    pass


class JSONParsingError(PackageMapperException):
    """Exception that is risen when a JSON file is not a valid JSON"""

    pass


class JSONStructureError(PackageMapperException):
    """Exception that is risen when JSON doesn't have expected fields"""

    pass


def is_branch_or_version(string):
    """Tries to figure out if passed argument is branch or version.
    Returns 'branch', 'version', or False if deduction failed.
    Branch is either 'master' or something like 3.12.x;
    version is something like 3.12.5,
    optionally followed by letter (3.12.5b) for aplha/beta/gamma...zeta,
    optionally followed by release (3.12.5-2).
    """
    if string == "master" or re.match("3\.\\d+\.x$", string):
        return "branch"
    if re.match("3\\.\\d+\\.\\d+[a-z]?(-\\d+)?$", string):
        return "version"
    return None


class PackageMapper:
    """Class responsible for updating packages_mapping.json file
    Currently it's tailored for cfengine needs.
    """

    def __init__(self, github, slack, dispatcher, username):
        self.github = github
        self.slack = slack
        self.username = username
        dispatcher.register_command(
            keyword="packages_mapping",
            callback=lambda branches: self.run(branches),
            parameter_name="branches",
            short_help="Add packages to packages_mapping.json",
            long_help="Scan releases.json for last release of given branches and add all of their packages to packages_mapping file",
        )

    def run(self, inputs):
        """Update the packages_mapping file and create PR"""
        # prepare repo
        repo_name = "system-testing"
        upstream_name = "cfengine"
        local_path = "../" + repo_name
        repo = GitRepo(local_path, repo_name, upstream_name, self.username, "master")
        timestamp = re.sub("[^0-9-]", "_", str(datetime.datetime.today()))
        new_branchname = "packages_mapping-{}".format(timestamp)
        repo.checkout(new_branchname, new=True)
        # load current file
        packages_mapping_file_path = "deployment_tests/packages_mapping.json"
        try:
            packages_mapping_contents = repo.get_file(packages_mapping_file_path)
        except FileNotFoundError as e:
            raise RepoFileNotFoundException(
                "file %s not found in repo. Is repo broken?"
                % packages_mapping_file_path
            ) from e
        try:
            packages_mapping = json.loads(
                packages_mapping_contents, object_pairs_hook=collections.OrderedDict
            )
        except json.decoder.JSONDecodeError as e:
            raise JSONParsingError(
                "file %s is not a valid JSON" % packages_mapping_file_path
            ) from e

        # sample of the file
        # {
        #   "packages": {
        #     "3.6.6": {
        #       "agent": {
        #         "community": {
        #           "PACKAGES_i386_linux_debian_4": {
        #             "url": "https://cfengine-package-repos.s3.amazonaws.com/community_binaries/cfengine-community_3.6.6-1_i386.deb"
        #           },
        for value in inputs.split(","):
            value_type = is_branch_or_version(value)
            assert value_type, "couldn't decide if [%s] is branch or version" % value
            self.slack.reply(
                "Updating packages mapping for %s %s " % (value_type, value)
            )
            result = {"agent": {}, "hub": {}}
            for product, codename in [
                ("community", "community"),
                ("enterprise", "nova"),
            ]:
                if value_type == "version":
                    version = value
                    branch = re.sub("^(\\d+\\.\\d+\\.).*", "\\1x", version)
                    release_url = "https://cfengine.com/release-data/%s/%s.json" % (
                        product,
                        version,
                    )
                else:
                    branch = value
                    releases_url = (
                        "https://cfengine.com/release-data/%s/releases.json" % product
                    )
                    releases_request = requests.get(releases_url)
                    if not releases_request.ok:
                        raise URLDownloadFailureException(
                            "failed to download %s, return code %d"
                            % (releases_url, releases_request.status_code)
                        )
                    try:
                        releases_data = releases_request.json()
                    except json.decoder.JSONDecodeError as e:
                        raise JSONParsingError(
                            "file %s is not a valid JSON" % releases_url
                        ) from e
                    if "releases" not in releases_data:
                        raise JSONStructureError(
                            'no "releases" in %s JSON' % releases_url
                        )
                    try:
                        release_url, version = next(
                            (release["URL"], release["version"])
                            for release in releases_data["releases"]
                            if "lts_branch" in release
                            and release["lts_branch"] == branch
                            and "latest_on_branch" in release
                            and release["latest_on_branch"]
                        )
                    except StopIteration as e:
                        raise JSONStructureError(
                            'no release with "lts_branch"=="%s" and "latest_on_branch"==true in %s JSON'
                            % (branch, releases_url)
                        ) from e

                packages = self.collect_packages(release_url)
                # masterfiles hack #1: different parts of code expect the package to be called differently.
                # Instead of fixing it properly, we will just support both namings
                packages["VIRTUAL_PACKAGES_masterfiles"] = packages[
                    "PACKAGES_VIRTUAL_PACKAGES_masterfiles"
                ]
                # sort packages into agent/hub ones
                if product == "community":
                    # for community, they are the same
                    hub_packages = agent_packages = packages
                else:
                    # masterfiles hack #2: different parts of code expect package to be in different groups
                    # ('hub' vs 'agent'). Instead of fixing it properly, we will just include it in both.
                    hub_packages = {
                        platform: value
                        for (platform, value) in packages.items()
                        if ("_HUB_" in platform) or ("masterfiles" in platform)
                    }
                    agent_packages = {
                        platform: value
                        for (platform, value) in packages.items()
                        if ("_HUB_" not in platform)
                    }
                result["agent"][codename] = agent_packages
                result["hub"][codename] = hub_packages
            # note that following code uses "branch" and "version" variables
            # they are left from last iteration of the above loop and should be
            # the same in all loop iterations
            packages_mapping["packages"][version] = result
            repo.put_file(
                packages_mapping_file_path, json.dumps(packages_mapping, indent=2)
            )
            # update version in upgrade_from.json
            branch_nox = re.sub("\\.x$", "", branch)
            upgrade_from_file_path = "deployment_tests/upgrade_from.json"
            try:
                upgrade_from_content = repo.get_file(upgrade_from_file_path)
            except FileNotFoundError as e:
                raise RepoFileNotFoundException(
                    "file %s not found in repo. Is repo broken?"
                    % upgrade_from_file_path
                ) from e
            try:
                upgrade_from = json.loads(
                    upgrade_from_content, object_pairs_hook=collections.OrderedDict
                )
            except json.decoder.JSONDecodeError as e:
                raise JSONParsingError(
                    "file %s is not a valid JSON" % upgrade_from_file_path
                ) from e
            upgrade_from["latest_version"][branch_nox] = version
            repo.put_file(upgrade_from_file_path, json.dumps(upgrade_from, indent=4))
            repo.commit("Add %s packages to packages_mapping" % version)
        repo.push(new_branchname)
        pr_text = self.github.create_pr(
            target_repo="{}/{}".format(upstream_name, repo_name),
            target_branch="master",
            source_user=self.username,
            source_branch=new_branchname,
            title="Add %s packages to packages_mapping" % inputs,
            text="",
        )
        self.slack.reply(pr_text, True)

    def collect_packages(self, url):
        """Given a release URL, returns a dict where keys are platform names, and values are {'url': 'http...'}"""
        release_request = requests.get(url)
        if not release_request.ok:
            raise URLDownloadFailureException(
                "failed to download %s, return code %d"
                % (url, release_request.status_code)
            )
        try:
            release_data = release_request.json()
        except json.decoder.JSONDecodeError as e:
            raise JSONParsingError("file %s is not a valid JSON" % url) from e
        if "artifacts" not in release_data:
            raise JSONStructureError('no "artifacts" in %s JSON' % url)
        # release_data['artifacts'] is a dictionary (called 'table'), each element is a list
        # to flattern it:
        # [item for table in release_data['artifacts'] for item in release_data['artifacts'][table]]
        # to choose only items with defined platforms (they are called 'package' and might be undefined)
        return {
            item["package"]: {"url": item["URL"]}
            for table in release_data["artifacts"]
            for item in release_data["artifacts"][table]
            if "package" in item and "URL" in item and not item["URL"].endswith("bff")
        }
