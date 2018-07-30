import os
import sys
import json
import argparse
import requests
import datetime
import hashlib
import random
import re
import traceback
import subprocess
import logging as log
import urllib.request
from copy import copy
from time import sleep
from requests.auth import HTTPBasicAuth

# Global constants for convenience

nick = "nickanderson"
vratislav = "vpodzime"
craig = "craigcomstock"
ole = "olehermanse"
aleksei = "Lex-2008"
tom = "cf-bottom"
karl = "karlhto"

trusted = [nick, vratislav, craig, ole, aleksei, karl]

repos = {
    "cfengine/core": [ole, vratislav],
    "cfengine/enterprise": [ole, vratislav, craig],
    "cfengine/nova": [ole, vratislav, craig],
    "cfengine/masterfiles": [craig, nick],
    "cfengine/buildscripts": [craig, aleksei],
    "cfengine/documentation": [nick, craig],
    "cfengine/contrib": [nick],
    "cf-bottom/self": [ole, vratislav, tom, karl]
}


def confirmation(msg):
    print(msg)
    choice = input("Accept? ")
    choice = choice.strip().lower()
    return choice == "y" or choice == "yes"


def get_maintainers(repo, exclude=None):
    if not exclude:
        exclude = []
    assert type(exclude) is list

    defaults = [ole, vratislav]

    reviewers = []

    if repo in repos:
        reviewers += repos[repo]
    for person in exclude:
        if person in reviewers:
            reviewers.remove(person)
    if len(reviewers) == 0:
        reviewers = copy(defaults)
    return reviewers


def pretty(data):
    return json.dumps(data, indent=2)


class Jenkins():
    def __init__(self, user, token, crumb):
        self.user = user
        self.token = token
        self.crumb = crumb

        self.auth = HTTPBasicAuth(user, token)
        self.headers = {"Jenkins-Crumb": crumb}

        self.url = "https://ci.cfengine.com/"
        self.job_name = "pr-pipeline"
        self.job_url = "{}job/{}/".format(self.url, self.job_name)
        self.trigger_url = "{}buildWithParameters/api/json".format(self.job_url)

    def post(self, path, data):
        r = requests.post(path, data=data, headers=self.headers, auth=self.auth)
        assert r.status_code >= 200 and r.status_code < 300
        print(r.headers)
        try:
            return r.headers, r.json()
        except:
            return r.headers, r.text

    def trigger(self, prs=None, branch="master", title=None):
        path = self.trigger_url
        params = {}
        repo_names = ",".join([k.lower() for k in prs])
        if prs:
            for repo in prs:
                param_name = repo.upper().replace("-", "_")
                assert " " not in param_name
                param_name = param_name + "_REV"
                params[param_name] = str(prs[repo])
        params["BASE_BRANCH"] = str(branch)
        if title is not None:
            description = "{} ({} {}@{})".format(title, "cf-bottom", repo_names, branch)
        else:
            description = "Unnamed build (cf-bottom)"
        params["BUILD_DESC"] = description
        return self.post(path, params)

    def wait_for_queue(self, url):
        log.debug("Queue URL: {}".format(url))
        queue_item = {}
        while "executable" not in queue_item:
            log.info("Waiting for jenkins build in queue")
            sleep(1)
            r = requests.get(url + "api/json")
            assert r.status_code >= 200 and r.status_code < 300
            queue_item = r.json()
        log.debug(pretty(queue_item))

        num = queue_item["executable"]["number"]
        url = queue_item["executable"]["url"]
        return num, url


class GitHub():
    def __init__(self, token):
        self.token = token
        self.headers = {"Authorization": "token {}".format(token), "User-Agent": "cf-bottom"}
        self.get_cache = {}

    def path(self, path):
        if path.startswith("/"):
            path = "https://api.github.com" + path
        return path

    def get(self, path):
        log.debug("GET {}".format(path))
        path = self.path(path)
        if path in self.get_cache:
            log.debug("Found in cache")
            return self.get_cache[path]
        r = requests.get(path, headers=self.headers)
        log.debug("RESPONSE {}".format(r.status_code))

        assert r.status_code >= 200 and r.status_code < 300
        data = r.json()
        log.debug(pretty(data))
        self.get_cache[path] = data
        if (not isinstance(data, list) or 'link' not in r.headers
                or 'rel="next"' not in r.headers['link']):
            # no need to paginate
            return data
        all_links = r.headers['link'].split(',')
        next_link = [link for link in all_links if 'rel="next"' in link]
        next_link = re.search('<(.*)>', next_link[0]).group(1)
        log.debug('paginating from {} to {}'.format(path, next_link))
        return data + self.get(next_link)

    def put(self, path, data):
        log.critical("PUT has not been implemented yet!")
        raise NotImplementedError

    def api_log(self, msg):
        log.debug("{}".format(msg))
        with open("api.log", "a") as f:
            f.write(msg + "\n")

    def post(self, path, data, check_status_code=True):
        self.api_log("POST {} {}".format(path, data))
        path = self.path(path)
        r = requests.post(path, headers=self.headers, json=data)
        log.debug("RESPONSE {}".format(r.status_code))
        if check_status_code:
            assert r.status_code >= 200 and r.status_code < 300, r.text
        data = r.json()
        log.debug(pretty(data))
        return data

    def create_pr(
            self,
            target_repo,
            target_branch,
            source_user,
            source_branch,
            title,
            text,
            simple_output=True):
        """Sends request to GitHub to create a pull request.
        Args:
            target_repo - repository where to create PR, for example 'cfengine/core'
            target_branch - branch to which to create PR, for example '3.12.x'
            source_user - user who forked target_repo - changes from his fork
                will be in PR. For example 'Lex-2008'. Note that we do NOT
                specify name of repo - github finds it automatically - looks
                like any given user can fork any repo only once.
            source_branch - branch in source_user's fork of target_repo from
                which to take changes
            title - title to assign to the PR (can be changed later by user)
            text - longer description of PR (can be changed later by user)
            simple_output - format of return value, see below
        Returns:
            Depending on simple_output, either:
            * String 'PR: <url>' if simple_output=True, or
            * nested dict based on JSON object representing the PR, shown at
              https://developer.github.com/v3/pulls/#response-2
        """

        data = {
            "title": title,
            "head": source_user + ':' + source_branch,
            "base": target_branch,
            "body": text,
            "maintainer_can_modify": True
        }
        pr = self.post("/repos/{}/pulls".format(target_repo), data, False)
        if not simple_output:
            return pr
        if not 'html_url' in pr:
            return 'PR creation failed with error:\n```\n{}\n```\n'\
                    .format(pretty(pr))
        else:
            return 'PR: {}'.format(pr['html_url'])

    @staticmethod
    def repo_path(owner, repo):
        return "/repos/{}/{}".format(owner, repo)

    @staticmethod
    def comment_path(owner, repo, issue):
        return "/repos/{}/{}/issues/{}/comments".format(owner, repo, issue)


class GitHubInterface():
    """class responsible for providing high-level user-visible commands"""

    def __init__(self, github, slack, dispatcher):
        self.github = github
        self.slack = slack
        try:
            with open('github_usernames.json') as f:
                self.github_usernames = json.load(f)
        except:
            self.github_usernames = {}
        dispatcher.register_command(
            'github', lambda username: self.set_account(username), 'username',
            'Register your github username',
            'Saves association between Slack and Github account names. ' +
            'Required for `repo` and `pr` commands')
        dispatcher.register_command(
            'repos', lambda: self.update_repos(), False,
            'Find your forks of private cfengine and mendersoftware repos',
            "There is no single API call to list all visible private repos for " +
            "a given user, so we have to loop through all cfengine and mender " +
            "private repos trying to find a fork belonging to current user. " +
            "This takes time so instead of doing it on every `pr` command, " +
            "we store this in cache. And this command refreshes the cache")
        dispatcher.register_command(
            'pr', lambda: self.create_pr_magic(), False,
            'make pull request from the branch you last pushed to', "")

    def set_account(self, username):
        """Saves association between Slack username and GitHub account.
        Slack username is author of current message being processed by bot,
        Github username passed as argument.
        """

        self.github_usernames[self.slack.reply_to_user] = username
        with open('github_usernames.json', 'w') as f:
            json.dump(self.github_usernames, f, indent=2)
        self.slack.reply(("I will remember that your github username is {}. "+
                "Now say \"<@{}> repos\" for me to update list of your private repos")\
                .format(username, self.slack.my_username), True)

    def get_github_name(self):
        """Returns Github username belonging to author of current Slack message.
        If there is none (i.e. he didn't specify it) - answer with a Slack message
        and return None.
        Calling method should work correctly if returned value is None!
        """
        if not self.slack.reply_to_user in self.github_usernames:
            self.slack.reply(
                (
                    "I don't know your github username. " + "Please say \"<@{}> github: USERNAME\" "
                    + "to identify yourself").format(self.slack.my_username), True)
            return None
        return self.github_usernames[self.slack.reply_to_user]

    def update_repos(self, username=None):
        """Find and save list of all private repos belonging to a user.
        Args:
            username - optional Github username of a user whose repos to update.
            If it's not passed or is falsy, get github username of a user whos
            Slack message we're currently processing.
        Reason:
            This is needed because Github doesn't provide a nice API to see
            other user's _private_ repos, even if we have access to them.
            i.e. if users cf-bottom and Lex-2008 are both part of 'cfengine' org,
            and Lex-2008 forked cfengine/secrets *private* repo, the only way
            for cf-bottom to reach this repo is:
            * Enumerate all private repos of cfengine org
            * And for each of them, find fork(s) belonging to Lex-2008
            This takes some time, so to speed things up we store this in cache
            and update periodically (TODO) or by request.
        """
        if not username:
            username = self.get_github_name()
        if not username:
            return
        message = (
            'Looking for all forks of private repos from ' +
            'cfengine and mendersoftware orgs for {} user...').format(username)
        log.info(message)
        self.slack.reply(message)
        user_repos = []
        log.info('getting org repos')
        # TODO: get orgs dynamically
        org_repos = self.github.get("/orgs/cfengine/repos?type=private")
        org_repos += self.github.get("/orgs/mendersoftware/repos?type=private")
        org_repos_with_forks = [repo for repo in org_repos if repo['forks'] > 0]
        for repo in org_repos_with_forks:
            log.info('getting forks for ' + repo['full_name'])
            repo_forks = self.github.get(repo['forks_url'])
            user_forks = [repo for repo in repo_forks if repo['owner']['login'] == username]
            user_repos += user_forks
            if len(user_forks) > 0:
                log.info('found repos:' + str(len(user_forks)))
        # TODO: here we assume that user repos always start with username.
        # Make it more explict or cleanup
        user_repo_names = [repo['name'] for repo in user_repos]
        os.makedirs('github_repos', exist_ok=True)
        with open('github_repos/{}.json'.format(username), 'w') as f:
            json.dump(user_repo_names, f, indent=2)
        message = (('I will remember that you have {} private repos:'+
                '\n```\n{}\n```\n'+
                'Next time you add a new private fork you want me to be aware of, '+
                'say \"<@{}> repos\" so I refreshed the list. '+
                "Note that public repos are easy-listable, so you don't need to "+
                "bother about them").\
                format(len(user_repo_names),
                    '\n'.join(sorted(user_repo_names)),
                    self.slack.my_username))
        log.info(message)
        self.slack.reply(message, True)

    def get_user_repos(self, username):
        """Returns list of private repos known to belong to GutHub user username.
        Updates such list if can't be loaded from file.
        """
        try:
            with open('github_repos/{}.json'.format(username)) as f:
                return json.load(f)
        except:
            self.update_repos(username)
            with open('github_repos/{}.json'.format(username)) as f:
                return json.load(f)
        # TODO: maybe print something if the list is empty?

    def find_last_repo(self, username):
        """Returns name of repository belonging to GitHub user username with highest
        (most recent) 'pushed' date
        """
        repo_names = self.get_user_repos(username)
        if len(repo_names) == 0:
            return None
        user_repos = [self.github.get("/repos/{}/{}".format(username, repo)) for repo in repo_names]
        open_repo = self.github.get("/users/{}/repos?sort=pushed".format(username))[0]
        log.info('adding open repo: ' + open_repo['name'])
        user_repos.append(open_repo)
        date_repos = dict([(repo['pushed_at'], repo['name']) for repo in user_repos])
        last_date = sorted(date_repos.keys())[-1]
        return date_repos[last_date]

    def find_last_branch_in_repo(self, username, repo):
        """Returns name of branch in username/repo repository with highest
        (most recent) 'committed' date
        """
        repo_branches = self.github.get("/repos/{}/{}/branches"\
                .format(username, repo))
        date_branches = {}
        for branch in repo_branches:
            branch_name = branch['name']
            branch_commit = self.github.get("/repos/{}/{}/commits/{}"\
                    .format(username, repo, branch_name))
            branch_date = branch_commit['commit']['committer']['date']
            log.info('branch {} has date {}'.format(branch_name, branch_date))
            date_branches[branch_date] = branch_name
        last_date = sorted(date_branches.keys())[-1]
        return date_branches[last_date]

    def find_parent_repo(self, username, repo):
        """Returns full name (cfengine/core) of a repository from which
        username/repo repository was forked from. If it can't be found for any
        reason, returns username/repo itself
        """
        repo_info = self.github.get("/repos/{}/{}".format(username, repo))
        try:
            return repo_info['parent']['full_name']  # cfengine/core
        except:
            log.debug('using current repo as parent')
            return '{}/{}'.format(username, repo)

    def find_parent(self, username, repo, last_branch):
        """Returns tuple of parent repository (found by find_parent_repo function)
        and parent branch for a given last_branch branch in username/repo repository.
        i.e. branch where last_branch should most probably be merged into.
        This is done on prefix match - if last_branch is called '3.10-something',
        then it's probably should be merged into branch '3.10.x' in parent_repo.
        Otherwise, parent_branch defaults to 'master'
        """
        parent_repo = self.find_parent_repo(username, repo)
        parent_branches = self.github.get("/repos/{}/branches".format(parent_repo))
        parent_branch = 'master'
        for branch in parent_branches:
            branch_name = branch['name']
            short_branch_name = re.sub('.x$', '', branch_name)
            log.debug('trying branch ' + branch_name)
            if last_branch.startswith(short_branch_name):
                log.debug('it matches! old parent {} new parent {}'\
                        .format(parent_branch, branch_name))
                if parent_branch == 'master':
                    parent_branch = branch_name
                else:
                    # we already found one candidate to be a parent branch.
                    # Use candidate with shortest prefix.
                    # i.e. if we have three branches named like this:
                    # * feature
                    # * feature-fix
                    # * feature-fixup
                    # then we assume that "feature-fixup"
                    # should be merged to "feature"
                    if len(parent_branch) > len(branch_name):
                        parent_branch = branch_name
        return (parent_repo, parent_branch)

    def create_pr_magic(self):
        """Create pull request for a branch where author of current slack
        message last pushed to
        """
        username = self.get_github_name()
        if not username:
            return
        message = 'Creating PR for {} user. Finding the last pushed-to repo...'\
                .format(username)
        log.info(message)
        self.slack.reply(message)
        repo = self.find_last_repo(username)
        if not repo:
            return
        message = ("You last pushed to {} repo. "+
                "Looking for the branch with most recent commit...").\
                format(repo)
        log.info(message)
        self.slack.reply(message)
        last_branch = self.find_last_branch_in_repo(username, repo)
        log.info('last branch: ' + last_branch)
        # now, try to find a parent for it.
        (parent_repo, parent_branch) = self.find_parent(username, repo, last_branch)
        log.info('parent branch: ' + parent_branch)
        pr_text = self.github.create_pr(
            parent_repo, parent_branch, username, last_branch, last_branch + ' PR', '')
        message = ("Found last branch: {}, corresponding parent branch: {} "+
                "in parent repo: {}. {}")\
                .format(last_branch, parent_branch, parent_repo, pr_text)
        log.info(message)
        self.slack.reply(message, True)


class Comment():
    def __init__(self, data):
        self.data = data
        self.author = data["user"]["login"]
        self.body = data["body"]

    def __str__(self):
        return "{}: {}".format(self.author, self.body)

    def __contains__(self, value):
        return value == self.author or value in self.body


class Comments():
    def __init__(self, data, github):
        self.data = data
        self.github = github

        self.comments = [Comment(c) for c in data]

        comments = data
        self.users = [comment["user"]["login"] for comment in comments]
        self.bodies = [comment["body"] for comment in comments]

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        return self.comments[index]


class PR():
    def __init__(self, data, github):
        self.data = data  # JSON dict from GitHub API
        self.github = github  # GitHub object with http methods and credentials

        self.comments_url = data["comments_url"]  # POST comments to this URL
        self.author = data["user"]["login"]  # PR Author / Submitter
        self.repo = data["base"]["repo"]["full_name"]  # cfengine/core
        self.short_repo_name = data["base"]["repo"]["name"]

        self.base_branch = data["base"]["ref"]
        self.base_user = data["base"]["user"]["login"]

        self.title = data["title"]
        self.number = data["number"]
        self.api_url = data["url"]
        self.reviews_url = self.api_url + "/reviews"

        self.labels = []
        if "labels" in data:
            self.labels = [label["name"].lower() for label in data["labels"]]

        self.comments = Comments(self.github.get(self.comments_url), github)

        self.maintainers = get_maintainers(self.repo)
        self.reviewers = get_maintainers(self.repo, exclude=[self.author])
        if self.author in self.reviewers:
            self.reviewers.remove(self.author)
        if tom in self.reviewers:
            self.reviewers.remove(tom)
        if len(self.reviewers) > 1 and nick in self.reviewers:
            self.reviewers.remove(nick)
        self.reviewer = random.choice(self.reviewers)

        self.reviews = self.github.get(self.reviews_url)
        self.approvals = []
        for r in self.reviews:
            if r["state"] == "APPROVED":
                self.approvals.append(r["user"]["login"])

        # This overwrites for every PR, intentionally, it is just used for
        # easier prototyping/development
        self.dump_to_file()

    def dump_to_file(self, path="tmp_pr.json"):
        with open(path, "w") as f:
            f.write(pretty(self.data))

    def has_label(self, label_name):
        label_name = label_name.lower()
        return label_name in self.labels


class GitRepo():
    """Class responsible for working with locally checked-out repository"""

    def __init__(self, dirname, url):
        self.dirname = dirname
        self.url = url
        self.username = tom
        self.usermail = tom + '@cfengine.com'

        if os.path.exists(dirname):
            # assume it's configured properly
            self.run_command('fetch')
        else:
            # TODO: configure it properly:
            self.run_command('clone', '--no-checkout', url, dirname)

    def run_command(self, *command, **kwargs):
        """Runs a git command against git repo.
        Syntaxically this function tries to be as close to subprocess.run
        as possible, just adding 'git' with some extra parameters in the beginning
        """
        git_command = [
            'git', '-C', self.dirname, '-c', 'user.name=' + self.username, '-c',
            'user.email=' + self.usermail, '-c', 'push.default=simple'
        ]
        git_command.extend(command)
        if 'check' not in kwargs:
            kwargs['check'] = True
        if 'capture_output' in kwargs:
            kwargs['stdout'] = subprocess.PIPE
            kwargs['stderr'] = subprocess.PIPE
            del kwargs['capture_output']
        if command[0] == 'clone':
            # we can't `cd` to target folder when it does not exist yet,
            # so delete `-C self.dirname` arguments from git command line
            del git_command[1]
            del git_command[1]
        kwargs['universal_newlines'] = True
        log.debug('running command: {}'.format(' '.join(git_command)))
        return subprocess.run(git_command, **kwargs)

    def checkout(self, branch, new=False):
        """Checkout given branch, optionally creating it.
        Note that it's an error to create-and-checkout branch which already exists.
        """
        if new:
            self.run_command('checkout', '-b', branch)
        else:
            self.run_command('checkout', branch)

    def get_file(self, path):
        """Returns contents of a file as a single string"""
        with open(self.dirname + '/' + path) as f:
            return f.read()

    def put_file(self, path, data, add=True):
        """Overwrites file with data, optionally running `git add {path}` afterwards"""
        with open(self.dirname + '/' + path, 'w') as f:
            f.write(data)
        if add:
            self.run_command('add', path)

    def commit(self, message):
        """Creates commit with message"""
        self.run_command('commit', '-m', message, '--allow-empty')

    def push(self, branch_name):
        """Pushes local branch to remote repo"""
        if branch_name:
            self.run_command('push', '--set-upstream', 'origin', branch_name)
        else:
            self.run_command('push')


class Slack():
    """Class responsible for all iteractions with Slack, EXCEPT for receiving
    messages (They are received as HTTPS requests from Slack to a webserver,
    which currently feeds them to stdin of this script running with `--talk`
    argument)
    """

    def __init__(self, bot_token, app_token):
        self.bot_token = bot_token
        self.app_token = app_token
        self.my_username = 'cf-bottom'

    def api(self, name):
        return 'https://slack.com/api/' + name

    def post(self, url, data={}):
        if not url.startswith('http'):
            url = self.api(url)
        if not 'token' in data:
            data['token'] = self.bot_token
        r = requests.post(url, data)
        assert r.status_code >= 200 and r.status_code < 300
        try:
            log.debug(pretty(r.json()))
            return r.json()
        except:
            log.debug(pretty(r.text))
            return False

    def send_message(self, channel, text):
        """Sends a message to a channel"""
        if not channel:
            return
        self.post('chat.postMessage', data={"channel": channel, "text": text})

    def set_reply_to(self, message):
        """Saves parameters of original message (channel and username) for
        easy _reply_ function
        """
        self.reply_to_channel = message['channel']
        self.reply_to_user = message['user']

    def reply(self, text, mention=False):
        """Replies to saved channel, optionally mentioning saved user"""
        if mention:
            text = '<@{}>: {}'.format(self.reply_to_user, text)
        self.send_message(self.reply_to_channel, text)


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


class CommandDispatcher():
    """Class responsible for processing user input (Slack messages) and
    dispatching relevant commands
    """

    def __init__(self, slack):
        self.slack = slack
        self.help_lines = [
            'List of commands bot recognises ' + '(prefix each command with bot name)'
        ]
        self.commands = [{}, {}]
        self.register_command(
            'help', lambda: self.show_help(), False, 'Show this text',
            'Shows overview of all commands')

    def register_command(self, keyword, callback, parameter_name, short_help, long_help=''):
        """Register a command as recognised by Tom.
        Args:
            keyword - text that Tom should react to
            callback - function that should be called when Tom receives a
                message with keyword
            parameter_name - name of parameter for commands with parameter, or
                False for commands without
            short_help - short description of command (Tom prints it in reply
                to `@cf-bottom help` command)
            long_help - long description of command (Tom will print it in reply
                to `@cf-bottom help on <keyword>` command - TODO: implement)
        """
        parameters_count = 1 if parameter_name else 0
        self.commands[parameters_count][keyword] = {'callback': callback, 'long_help': long_help}
        if parameter_name:
            self.help_lines.append(
                '{}: _{}_\n-  {}'.format(keyword, parameter_name.upper(), short_help))
        else:
            self.help_lines.append('{}\n-  {}'.format(keyword, short_help))

    def parse_text(self, text):
        """Analyze user message and react on it - call a registered command"""
        # remove bot username from string
        text = re.sub('<@{}> *:? *'.format(self.slack.my_username), '', text)
        m = re.match(' *([^:]*)(?:[:] *([^ ]*))?', text)
        keyword = m.group(1)
        argument = m.group(2)
        if argument:
            parameters_count = 1
            arguments = [argument]
        else:
            parameters_count = 0
            arguments = []
        if keyword in self.commands[parameters_count]:
            try:
                self.commands[parameters_count][keyword]['callback'](*arguments)
            except:
                self.slack.reply(
                    'I crashed on your command:' + '\n```\n{}\n```'.format(traceback.format_exc()),
                    True)
        else:
            self.slack.reply(("Unknown command. Say \"<@{}> help\" for "+
                "list of known commands")\
                .format(self.slack.my_username))

    def show_help(self):
        """Print basic help info"""
        self.slack.reply('\n\n'.join(self.help_lines))


class Tom():
    def __init__(self, secrets, interactive):
        github = secrets["GITHUB_TOKEN"]
        self.github = GitHub(github)

        user = secrets["JENKINS_USER"]
        token = secrets["JENKINS_TOKEN"]
        if not (user and token):
            sys.exit("Cannot start Tom without Jenkins credentials")
        crumb = secrets["JENKINS_CRUMB"]
        self.jenkins = Jenkins(user, token, crumb)

        self.slack_read_token = secrets["SLACK_READ_TOKEN"]
        bot_token = secrets["SLACK_SEND_TOKEN"]
        app_token = secrets["SLACK_APP_TOKEN"]
        self.slack = None
        if self.slack_read_token and bot_token and app_token:
            self.slack = Slack(bot_token, app_token)

        self.dispatcher = CommandDispatcher(self.slack)
        self.github_interface = GitHubInterface(self.github, self.slack, self.dispatcher)
        # self.updater = UpdateChecker(self.github, self.slack, self.dispatcher)
        self.interactive = interactive

    def post(self, path, data, msg=None):
        if self.interactive:
            print("I'd like to POST something")
            msg = "" if msg is None else msg
            msg += "Path: {}".format(path)
            msg += "Data: {}".format(data)
            if not confirmation(msg):
                return False
        self.github.post(path, data)
        return True

    def comment(self, pr, message):
        path = pr.comments_url
        pr_string = "PR: {} ({}#{})".format(pr.title, pr.repo, pr.number)
        data = {"body": str(message)}
        commented = self.post(path, data, pr_string)
        if commented:
            print("Commented on {}".format(pr_string))
            print(message)
            print("")

    def ping_reviewer(self, pr):
        if "cf-bottom" in pr.comments.users:
            log.info("I have already commented :)")
        elif len(pr.comments) > 0:
            log.info("There are already comments there, so I won't disturb")
        elif pr.has_label("WIP") or "WIP" in pr.title.upper():
            log.info("This is a WIP PR, so I won't disturb")
        else:
            thanks = random.choice(["Thanks", "Thank you"])
            pull = random.choice(["PR", "pull request"])
            comment = "{thanks} for submitting a {pr}! Maybe @{user} can review this?".format(
                thanks=thanks, pr=pull, user=pr.reviewer)
            self.comment(pr, comment)

    def review(self, pr):
        if tom not in pr.maintainers:
            return
        if tom in pr.approvals:
            return
        for person in pr.approvals:
            if person in pr.maintainers:
                log.info("Reviewing: {}".format(pr.title))
                log.info("Approved by: " + str(pr.approvals))
                body = "I trust @{}, approved!".format(person)
                event = "APPROVE"
                data = {"body": body, "event": event}
                self.post(pr.reviews_url, data)
                print("Approved PR: {}".format(pr.title))

    def comment_badge(self, pr, num, url):
        badge_icon = "https://ci.cfengine.com/buildStatus/icon?job=pr-pipeline&build={}".format(num)
        badge_link = "https://ci.cfengine.com/job/pr-pipeline/{}/".format(num)
        badge = "[![Build Status]({})]({})".format(badge_icon, badge_link)
        response = random.choice(["Alright", "Sure"])
        new_comment = "{}, I triggered a build:\n\n{}\n\n{}".format(response, badge, url)
        self.comment(pr, new_comment)

    def trigger_build(self, pr, comment):
        prs = {}
        prs[pr.short_repo_name] = pr.number
        #TODO: allow pr numbers in comments

        if self.interactive:
            msg = []
            msg.append(str(comment))
            msg.append("Triger build for: {}".format(pr.title))
            msg.append("PRs: {}".format(prs))
            msg = "\n".join(msg)
            if not confirmation(msg):
                return

        headers, body = self.jenkins.trigger(prs, branch=pr.base_branch, title=pr.title)

        queue_url = headers["Location"]

        num, url = self.jenkins.wait_for_queue(queue_url)

        print("Triggered build ({}): {}".format(num, url))
        self.comment_badge(pr, num, url)

    def handle_mention(self, pr, comment):
        deny = "@{} : I'm sorry, I cannot do that. @olehermanse please help.".format(comment.author)
        if comment.author not in trusted or pr.base_user != "cfengine":
            print("Denying mention from {} on base {}".format(comment.author, pr.base_user))
            self.comment(pr, deny)
            return
        body = comment.body.lower()
        trigger_words = ["jenkins", "pipeline", "build", "trigger"]
        for word in trigger_words:
            if word.lower() in body:
                self.trigger_build(pr, comment)
                return

        no_comprendo = "I'm not sure I understand, @{}.".format(comment.author)
        self.comment(pr, no_comprendo)

    def handle_comments(self, pr):
        for comment in reversed(pr.comments):
            if comment.author == "cf-bottom":
                return
            if "@cf-bottom" in comment:
                self.handle_mention(pr, comment)

    def handle_pr(self, pr):
        url = pr["url"].replace("https://api.github.com/repos/", "")
        log.info("Looking at: {} ({})".format(pr["title"], url))
        pr = PR(pr, self.github)

        self.ping_reviewer(pr)
        self.review(pr)
        self.handle_comments(pr)

    def run(self):
        self.repos = self.github.get("/user/repos")
        self.repos += self.github.get("/orgs/cfengine/repos")

        # Remove duplicate repos:
        repos_map = {repo["full_name"]: repo for repo in self.repos}
        self.repos = [value for key, value in repos_map.items()]

        self.pulls = []
        for repo in self.repos:
            log.info("Fetching pull requests for {}".format(repo["full_name"]))
            pulls = self.github.get(repo["url"] + "/pulls")
            if pulls:
                self.pulls.extend(pulls)

        if self.pulls:
            log.info("Found {} open pull requests".format(len(self.pulls)))
        else:
            log.warning("Couldn't find any open pull requests!")

        for pull in self.pulls:
            self.handle_pr(pull)
        log.info("Tom successful")

    def talk(self):
        if not self.slack:
            sys.exit("Cannot start talk mode, Slack credentials missing")

        message = json.load(sys.stdin)

        log.debug(pretty(message))
        if 'token' not in message or message['token'] != self.slack_read_token:
            log.warning('unauthorised message, ignoring')
            return
        if 'authed_users' in message and len(message['authed_users']) > 0:
            self.slack.my_username = message['authed_users'][0]
        message = message['event']
        if not 'user' in message:
            # not a user-generated message
            # probably a bot-generated message
            log.warning('not a user message, ignoring')
            return
        self.slack.set_reply_to(message)
        self.dispatcher.parse_text(message['text'])


def run_tom(interactive, secrets_dir, talk_mode):
    secrets = {}
    names = [
        "GITHUB_TOKEN", "JENKINS_CRUMB", "JENKINS_USER", "JENKINS_TOKEN", "SLACK_READ_TOKEN",
        "SLACK_SEND_TOKEN", "SLACK_APP_TOKEN"
    ]
    for n in names:
        secrets[n] = get_var(n, secrets_dir)
    tom = Tom(secrets, interactive)
    if talk_mode:
        tom.talk()
    else:
        tom.run()


def get_var(name, dir="./"):
    var = None
    if name in os.environ:
        var = os.environ[name]
    else:
        try:
            with open(os.path.join(dir, name), "r") as f:
                var = f.read().strip()
        except (PermissionError, FileNotFoundError):
            pass
    return var


def get_args():
    argparser = argparse.ArgumentParser(description='CFEngine Bot, Tom')
    argparser.add_argument(
        '--interactive', '-i', help='Ask first, shoot questions later', action="store_true")
    argparser.add_argument(
        '--continuous', '-c', help='Run in a loop, exits on error/failures', action="store_true")
    argparser.add_argument(
        '--secrets', '-s', help='Directory to read secrets', default="./", type=str)
    argparser.add_argument(
        '--talk',
        '-t',
        help="Run Tom in talk mode, when it reads Slack message from stdin",
        action="store_true")
    argparser.add_argument('--log-level', '-l', help="Detail of log output", type=str)
    args = argparser.parse_args()

    return args


def main():
    args = get_args()
    fmt = "[%(levelname)s] %(message)s"
    if args.log_level:
        numeric_level = getattr(log, args.log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError("Invalid log level: {}".format(args.log_level))
        log.basicConfig(level=numeric_level, format=fmt)
    else:
        log.basicConfig(format=fmt)
    log.getLogger("requests").setLevel(log.WARNING)
    log.getLogger("urllib3").setLevel(log.WARNING)
    if args.continuous:
        while True:
            run_tom(args.interactive, args.talk)
            print("Iteration complete, sleeping for 12 seconds")
            sleep(12)
    else:
        run_tom(args.interactive, args.secrets, args.talk)


if __name__ == "__main__":
    main()  # Don't add any variables to global scope.
