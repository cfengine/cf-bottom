import random
import requests
import re
import json
import logging as log
from copy import copy
import requests

from tom.utils import pretty


class GitHub():
    def __init__(self, token, user_agent):
        self.token = token
        self.headers = {"Authorization": "token {}".format(token), "User-Agent": user_agent}
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
        self.review_comments = Comments(
            self.get_review_comments(self.github.get(self.reviews_url)), github)

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

    def get_review_comments(self, reviews):
        all_review_comments = []
        for review in reviews:
            log.debug(
                "getting review_comments for: PR: {}, id: {}".format(
                    review["pull_request_url"], review["id"]))
            request_url = "/".join(self.review_url, review["id"], "comments")
            review_comment = self.github.get(request_url)
            all_review_comments.append(review_comment)
        return review_comments
