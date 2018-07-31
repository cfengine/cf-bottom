import re
import requests
import datetime
import hashlib
import urllib.request


class UpdateChecker():
    """Class responsible for doing dependency updates"""

    def __init__(self, github, slack, dispatcher):
        self.github = github
        self.slack = slack
        dispatcher.register_command(
            'deps', lambda branch: self.run(branch), 'branch', 'Run dependency updates',
            'Try to find new versions of dependencies on given branch ' + 'and create PR with them')

    def get_deps_list(self, branch='master'):
        """Get list of dependencies for given branch.
           Assumes proper branch checked out by `self.buildscripts` repo.
           Returns a list, like this: ["lcov", "pthreads-w32", "libgnurx"]
        """
        # TODO: get value of $EMBEDDED_DB from file
        embedded_db = 'lmdb'
        options_file = self.buildscripts.get_file('build-scripts/compile-options')
        options_lines = options_file.split('\n')
        filtered_lines = [x for x in options_lines if 'var_append DEPS' in x]
        only_deps = [re.sub('.*DEPS "(.*)".*', "\\1", x) for x in filtered_lines]
        # currently only_deps is list of space-separated deps,
        # i.e. each list item can contain several items, like this:
        # only_deps = ["lcov", "pthreads-w32 libgnurx"]
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
                    m.update(f.read(4096))
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
            version = re.search('-([0-9a-z.]*).tar', filename).group(1)
            separator = 'char'
        elif dep == 'pthreads-w32':
            version = re.search('w32-([0-9-]*)-rel', filename).group(1)
            separator = '-'
        else:
            version = re.search('[-_]([0-9.]*)\.', filename).group(1)
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

    def update_single_dep(self, dep):
        """Check if new version of dependency dep was released and create
        commit updating it in *.spec, dist, source, and README.md files
        """
        log.info('Checking new version of {}'.format(dep))
        dist_file_path = 'deps-packaging/{}/distfiles'.format(dep)
        source_file_path = 'deps-packaging/{}/source'.format(dep)
        dist_file = self.buildscripts.get_file(dist_file_path)
        source_file = self.buildscripts.get_file(source_file_path)
        dist_file = dist_file.strip()
        source_file = source_file.strip()
        old_filename = re.sub('.* ', '', dist_file)
        old_url = '{}{}'.format(source_file, old_filename)
        (old_version, separator) = self.extract_version_from_filename(dep, old_filename)
        new_version = self.find_new_version(old_url, old_version, separator)
        if new_version == old_version:
            # no update needed
            return False
        new_url = old_url.replace(old_version, new_version)
        message = 'Update {} from {} to {}'.format(dep, old_version, new_version)
        log.info(message)
        spec_file_path = 'deps-packaging/{}/cfbuild-{}.spec'.format(dep, dep)
        spec_file = self.buildscripts.get_file(spec_file_path)
        spec_file = spec_file.replace(old_version, new_version)
        new_filename = old_filename.replace(old_version, new_version)
        md5sum = self.checkfile(new_url, True)
        dist_file = '{}  {}'.format(md5sum, new_filename)
        source_file = source_file.replace(old_version, new_version)
        self.readme_lines = [
            self.maybe_replace(
                x, '* [{}]('.format(dep.replace('-hub', '')), old_version, new_version)
            for x in self.readme_lines
        ]
        readme_file = '\n'.join(self.readme_lines)
        self.buildscripts.put_file(dist_file_path, dist_file + '\n')
        self.buildscripts.put_file(spec_file_path, spec_file + '\n')
        self.buildscripts.put_file(source_file_path, source_file + '\n')
        self.buildscripts.put_file(self.readme_file_path, readme_file)
        self.buildscripts.commit(message)
        return message

    def run(self, branch):
        """Run the dependency update for a branch, creating PR in the end"""
        self.slack.reply("Running dependency updates for " + branch)
        # prepare repo
        self.buildscripts = GitRepo('../buildscripts', 'git@github.com:cfengine/buildscripts.git')
        self.buildscripts.checkout(branch)
        timestamp = re.sub('[^0-9-]', '_', str(datetime.datetime.today()))
        new_branchname = '{}-deps-{}'.format(branch, timestamp)
        self.buildscripts.checkout(new_branchname, True)
        self.readme_file_path = 'deps-packaging/README.md'
        readme_file = self.buildscripts.get_file(self.readme_file_path)
        self.readme_lines = readme_file.split('\n')
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
        # TODO: switch to cfengine/buildscripts eventually
        pr_text = self.github.create_pr(
            'Lex-2008/buildscripts', branch, 'Lex-2008', new_branchname,
            'Dependency updates for ' + branch, updates_summary)
        slack.reply("Dependency updates:\n```\n{}\n```\n{}".format(updates_summary, pr_text), True)
