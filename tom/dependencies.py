import re
import json
import requests
import collections
import datetime
import hashlib
import urllib.request
import logging as log
from tom.git import GitRepo
from tom.utils import pretty

class DependencyException(Exception):
    """Base class for all exceptions in this file"""
    pass

class ReleaseMonitoringException(DependencyException):
    """Exception that is risen if release-monitoring.org behaves unexpectedly"""
    pass



class UpdateChecker():
    """Class responsible for doing dependency updates
    Currently it's working only with cfengine/buildscripts repo, as described at
    https://github.com/mendersoftware/infra/blob/master/files/buildcache/release-scripts/RELEASE_PROCESS.org#minor-dependencies-update
    """

    def __init__(self, github, slack, dispatcher, username):
        self.github = github
        self.slack = slack
        self.username = username
        dispatcher.register_command(
                keyword='deps',
                callback=lambda branch: self.run(branch),
                parameter_name='branch',
                short_help='Run dependency updates',
                long_help='Try to find new versions of dependencies on given branch and create PR with them')
        dispatcher.register_command(
                keyword='depstable',
                callback=lambda branches: self.update_deps_version(branches),
                parameter_name='branches',
                short_help='Rebuild dependencies table',
                long_help='Enumerate used dependency versions and update dependency table. Argument is comma-separated list of branches, NO SPACES')

    def get_deps_list(self, branch='master'):
        """Get list of dependencies for given branch.
           Assumes proper branch checked out by `self.buildscripts` repo.
           Returns a list, like this: ["lcov", "pthreads-w32", "libgnurx"]
        """
        # TODO: get value of $EMBEDDED_DB from file
        embedded_db = 'lmdb'
        if branch == '3.7.x':
            options_file = self.buildscripts.get_file('build-scripts/install-dependencies')
        else:
            options_file = self.buildscripts.get_file('build-scripts/compile-options')
        options_lines = options_file.splitlines()
        if branch == '3.7.x':
            filtered_lines = (x for x in options_lines if re.match('\s*DEPS=".*\\$DEPS', x))
            only_deps = (re.sub('\\$?DEPS', '', x) for x in filtered_lines)
            only_deps = (re.sub('[=";]', '', x) for x in only_deps)
            only_deps = (x.strip() for x in only_deps)
        else:
            filtered_lines = (x for x in options_lines if 'var_append DEPS' in x)
            only_deps = (re.sub('.*DEPS "(.*)".*', "\\1", x) for x in filtered_lines)
        # currently only_deps is generator of space-separated deps,
        # i.e. each item can contain several items, like this:
        # list(only_deps) = ["lcov", "pthreads-w32 libgnurx"]
        # to "flattern" it we first join using spaces and then split on spaces
        # in the middle we also do some clean-ups
        only_deps = ' '.join(only_deps)\
                .replace('$EMBEDDED_DB', embedded_db)\
                .replace('libgcc ','')\
                .split(' ')
        # now only_deps looks like this: ["lcov", "pthreads-w32", "libgnurx"]
        log.debug(pretty(only_deps))
        return only_deps

    def increase_version(self, version, increment, separator='.'):
        """increase last part of version - so 1.2.9 becomes 1.2.10
           Args:
               version - old version represented as string
               increment - by how much to increase
               separator - separator character between version parts. Typical
                   values are '.' and '-'. Special case: if separator is 'char'
                   string, then increase last character by 1 - so version
                   '1.2b' becomes '1.2c'
                   (we assume that we never meet version ending with 'z')
           Returns:
             new version as a string
        """
        if separator == 'char':
            return version[:-1] + chr(ord(version[-1]) + increment)
        version_components = version.split(separator)
        version_components[-1] = str(int(version_components[-1]) + increment)
        return separator.join(version_components)

    def checkfile(self, url, md5=False):
        """Checks if file on given URL exists and optionally returns its md5 sum
           Args:
               url - URL to check (starting with http or ftp, other protocols might not work)
               md5 - set it to True to force downloading file and returning md5 sum
                   (otherwise, for http[s] we use HEAD request)
           Returns:
               True, False, or md5 of a linked file
        """
        log.debug('checking URL: ' + url)
        try:
            if not md5 and url.startswith('http'):
                log.debug('testing with HEAD')
                r = requests.head(url)
                return r.status_code >= 200 and r.status_code < 300
            else:
                log.debug('getting whole file')
                m = hashlib.md5()
                with urllib.request.urlopen(url) as f:
                    data = f.read(4096)
                    while data:
                        m.update(data)
                        data = f.read(4096)
                return m.hexdigest()
        except:
            return False

    def maybe_replace(self, string, match, old, new):
        """replaces `old` with `new` in `string` only if it contains `match`
            Does caseless compare by converting `string` to lowercase for comparison
            Args:
                string - string to work on
                match - string to look for, MUST BE lowercase
                old - string to replace
                new - string to replace with
        """
        if match not in string.lower():
            return string
        return string.replace(old, new)

    def extract_version_from_filename(self, dep, filename):
        if dep == 'openssl':
            # On different branches we use openssl from different sources
            # (this will be cleaned up soon). When downloading from github,
            # filename is OpenSSL_1_1_1.tar.gz, where 1_1_1 is version.
            # When downloading from openssl website, filename for same version
            # is openssl-1.1.1.tar.gz, and version is 1.1.1.
            # We first check for website-style version, and if it doesn't match
            # then we fallback to github-style version. If neither version is
            # found - match.group(1) will raise an exception.
            match = re.search('-([0-9a-z.]*).tar', filename)
            if not match:
                match = re.search('_([0-9a-z_]*).tar', filename)
            version = match.group(1)
            separator = 'char'
        elif dep == 'pthreads-w32':
            version = re.search('w32-([0-9-]*)-rel', filename).group(1)
            separator = '-'
        else:
            version = re.search('[-_]([0-9.]*)[\.-]',filename).group(1)
            separator = '.'
        return (version, separator)

    def find_new_version(self, old_url, old_version, separator):
        """Finds new version by iteratively increasing version in URL and
        checking if it's still possible to download a file.
        Returns highest version for which a file exists.
        Note that if old_version is 1.2.3, and somebody released version
        1.2.5 WITHOUT releasing 1.2.4 before that, then this function will NOT
        find it
        """
        increment = 0
        url_result = True
        while url_result:
            increment += 1
            new_version = self.increase_version(old_version, increment, separator)
            # note that we change version on URL level, not on filename level -
            # because sometimes version might be in directory name, too
            new_url = old_url.replace(old_version, new_version)
            url_result = self.checkfile(new_url)
            # note that url_result might be True, False, or string with md5 hash
        # Loop ends when `increment` points to non-existing version -
        # so we need to decrease it to point to last existing one
        increment -= 1
        if increment == 0:
            return old_version
        return self.increase_version(old_version, increment, separator)

    def get_version_from_monitoring(self, dep):
        """Gets latest version of a dependency from release-monitoring.org site.
        Returns latest version (string), or False if dependency not found in
        release-monitoring.json file.
        """
        if dep not in self.monitoring_ids:
            return False
        id = self.monitoring_ids[dep]
        url = 'https://release-monitoring.org/api/project/{}'.format(id)
        try:
            data = requests.get(url).json()
        except:
            raise ReleaseMonitoringException('Failed to do a request to release-monitoring.org website')
        try:
            return data['version']
        except:
            raise ReleaseMonitoringException('Failed to get version from data received from release-monitoring.org website')

    def get_current_version(self, dep):
        """Get current version of dependency dep"""
        # Note: this function partially duplicates next one.
        # It is done on purpose, since that one does some extra stuff.
        dist_file_path = 'deps-packaging/{}/distfiles'.format(dep)
        dist_file = self.buildscripts.get_file(dist_file_path)
        dist_file = dist_file.strip()
        old_filename = re.sub('.* ', '', dist_file)
        (old_version, separator) = self.extract_version_from_filename(dep, old_filename)
        return old_version

    def update_single_dep(self, dep):
        """Check if new version of dependency dep was released and create
        commit updating it in *.spec, dist, source, and README.md files
        """
        # Note: this function partially duplicates above one.
        # It is done on purpose, since it will need several other variables
        # afterwards: dist_file_path, old_filename, and separator.
        log.info('Checking new version of {}'.format(dep))
        dist_file_path = 'deps-packaging/{}/distfiles'.format(dep)
        dist_file = self.buildscripts.get_file(dist_file_path)
        dist_file = dist_file.strip()
        source_file_path = 'deps-packaging/{}/source'.format(dep)
        source_file = self.buildscripts.get_file(source_file_path)
        source_file = source_file.strip()
        old_filename = re.sub('.* ', '', dist_file)
        old_url = '{}{}'.format(source_file, old_filename)
        (old_version, separator) = self.extract_version_from_filename(dep, old_filename)
        new_version = self.get_version_from_monitoring(dep)
        if not new_version:
            log.warning('Dependency {} not found in release-monitoring.org or in data file'.format(dep))
            new_version = self.find_new_version(old_url, old_version, separator)
        if new_version == old_version:
            # no update needed
            return False
        new_filename = old_filename.replace(old_version, new_version)
        new_url = old_url.replace(old_version, new_version)
        md5sum = self.checkfile(new_url, True)
        if not md5sum:
            message = 'Update {} from {} to {} FAILED to download {}'.format(dep, old_version, new_version, new_url)
            log.warn(message)
            self.slack.reply(message)
            return False
        message = 'Update {} from {} to {}'.format(dep, old_version, new_version)
        log.info(message)
        dist_file = '{}  {}'.format(md5sum, new_filename)
        self.buildscripts.put_file(dist_file_path, dist_file + '\n')
        source_file = source_file.replace(old_version, new_version)
        self.buildscripts.put_file(source_file_path, source_file + '\n')
        self.readme_lines = [
            self.maybe_replace(
                x, '* [{}]('.format(dep.replace('-hub', '')), old_version, new_version)
            for x in self.readme_lines
        ]
        readme_file = '\n'.join(self.readme_lines)
        self.buildscripts.put_file(self.readme_file_path, readme_file)
        spec_file_path = 'deps-packaging/{}/cfbuild-{}.spec'.format(dep, dep)
        try:
            spec_file = self.buildscripts.get_file(spec_file_path)
        except:
            pass
        else:
            spec_file = spec_file.replace(old_version, new_version)
            self.buildscripts.put_file(spec_file_path, spec_file + '\n')
        self.buildscripts.commit(message)
        return message

    def collect_deps(self, branch):
        """List used dependencies for a branch, returns a dict like this:
            {"dep1": "version", "dep2": "version",...}
            """
        deps_versions = {}
        deps_list = self.get_deps_list(branch)
        for dep in deps_list:
            deps_versions[dep] = self.get_current_version(dep)
        return deps_versions

    def update_deps_version(self, branches):
        # prepare repo
        repo_name = 'buildscripts'
        upstream_name = 'cfengine'
        local_path = "../" + repo_name
        self.buildscripts = GitRepo(local_path, repo_name, upstream_name, self.username, 'master')

        branches = branches.split(',')

        # fetch versions from all branches
        deps_table = {}
        # deps_table is a 2d dict: deps_table[dep][branch]=version
        branch_column_widths = {}
        for branch in branches:
            branch_column_widths[branch] = len(branch)
            self.buildscripts.checkout(branch)
            self.buildscripts.run_command('pull')
            deps_versions = self.collect_deps(branch)
            # deps_versions is a dict: deps_versions[dep]=version
            for dep in deps_versions:
                if not dep in deps_table:
                    deps_table[dep] = collections.defaultdict(lambda: "-")
                deps_table[dep][branch] = deps_versions[dep]
                branch_column_widths[branch] = max(branch_column_widths[branch], len(deps_versions[dep]))

        # patch the readme
        self.buildscripts.checkout('master')
        self.readme_file_path = 'deps-packaging/README.md'
        readme_file = self.buildscripts.get_file(self.readme_file_path)
        readme_lines = readme_file.split('\n')
        has_notes = False # flag to say that we're in a table that has "Notes" column
        in_hub = False # flag that we're in Hub section
        for i, line in enumerate(readme_lines):
            if ' Hub ' in line:
                in_hub = True
            if not line.startswith('| '):
                continue
            if line.startswith('| CFEngine version '):
                has_notes = 'Notes' in line
                branches_text = ' | '.join([branch.ljust(branch_column_widths[branch]) for branch in branches])
                line = '| CFEngine version | ' + branches_text + (' | Notes |' if has_notes else ' |')
            elif line.startswith('|  --'):
                branches_text = ' | '.join(['-'*branch_column_widths[branch] for branch in branches])
                line = '|  --------------  | ' + branches_text + (' | ----- |' if has_notes else ' |')
            else:
                dep = re.match('\\|  ([a-z0-9-]*) ', line, flags=re.IGNORECASE)
                if dep:
                    dep = dep.group(1)
                else:
                    log.warn("didn't find dep in line [%s]", line)
                    continue
                if in_hub and dep == 'postgresql':
                    dep = 'postgresql-hub'
                if dep not in deps_table:
                    log.warn("unknown dependency in README: [%s] line [%s], will be EMPTY", dep, line)
                    deps_table[dep] = collections.defaultdict(lambda: "-")
                if has_notes:
                    note = re.search('\| [^|]* \|$', line)
                    if not note:
                        log.warn("didn't find note in line [%s]", line)
                        note = '|  |'
                    note = note.group(0) # group(0) is full matched string
                branches_text = ' | '.join(deps_table[dep][branch].ljust(branch_column_widths[branch]) for branch in branches)
                if in_hub:
                    dep = re.sub('-hub$', '', dep)
                line = '|  %-15s | %s %s' % (dep, branches_text, (note if has_notes else '|'))
            readme_lines[i] = line

        timestamp = re.sub('[^0-9-]', '_', str(datetime.datetime.today()))
        new_branchname = 'deptables-{}'.format(timestamp)
        self.buildscripts.checkout(new_branchname, new=True)
        readme_file = '\n'.join(readme_lines)
        self.buildscripts.put_file(self.readme_file_path, readme_file)
        self.buildscripts.commit('Update dependency tables')
        self.buildscripts.push(new_branchname)
        pr_text = self.github.create_pr(
            target_repo='{}/{}'.format(upstream_name, repo_name),
            target_branch='master',
            source_user=self.username,
            source_branch=new_branchname,
            title='Update dependency tables',
            text='')
        self.slack.reply("Dependency tables:\n{}".format(pr_text), True)

    def run(self, branch):
        """Run the dependency update for a branch, creating PR in the end"""
        self.slack.reply("Running dependency updates for " + branch)
        # prepare repo
        repo_name = 'buildscripts'
        upstream_name = 'cfengine'
        local_path = "../" + repo_name
        self.buildscripts = GitRepo(local_path, repo_name, upstream_name, self.username, branch)
        timestamp = re.sub('[^0-9-]', '_', str(datetime.datetime.today()))
        new_branchname = '{}-deps-{}'.format(branch, timestamp)
        self.buildscripts.checkout(new_branchname, new=True)
        self.readme_file_path = 'deps-packaging/README.md'
        readme_file = self.buildscripts.get_file(self.readme_file_path)
        self.readme_lines = readme_file.split('\n')
        self.monitoring_file_path = 'deps-packaging/release-monitoring.json'
        self.monitoring_ids = json.loads(self.buildscripts.get_file(self.monitoring_file_path))
        updates_summary = []
        only_deps = self.get_deps_list(branch)
        for dep in only_deps:
            single_result = self.update_single_dep(dep)
            if single_result:
                updates_summary.append(single_result)
                self.slack.reply(single_result)
        if len(updates_summary) == 0:
            self.slack.reply("Dependency checked, nothing to update")
            return
        self.buildscripts.push(new_branchname)
        updates_summary = '\n'.join(updates_summary)
        pr_text = self.github.create_pr(
            target_repo='{}/{}'.format(upstream_name, repo_name),
            target_branch=branch,
            source_user=self.username,
            source_branch=new_branchname,
            title='Dependency updates for ' + branch,
            text=updates_summary)
        self.slack.reply("Dependency updates:\n```\n{}\n```\n{}".format(updates_summary, pr_text), True)
