import os
import sys
import json
import argparse
import requests
import random
import re
import traceback
import subprocess
import logging as log
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
        if (not isinstance(data, list) or
                'link' not in r.headers or
                'rel="next"' not in r.headers['link']):
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

    def create_pr(self, target_repo, target_branch,
            source_user, source_branch, title, text, simple_output=True):
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
                "head": source_user+':'+source_branch,
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
        git_command = ['git', '-C', self.dirname,
                '-c', 'user.name='+self.username,
                '-c', 'user.email='+self.usermail,
                '-c', 'push.default=simple']
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
        with open(self.dirname+'/'+path) as f:
            return f.read()

    def put_file(self, path, data, add=True):
        """Overwrites file with data, optionally running `git add {path}` afterwards"""
        with open(self.dirname+'/'+path, 'w') as f:
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


class Tom():
    def __init__(self, secrets, interactive):
        github = secrets["GITHUB_TOKEN"]
        self.github = GitHub(github)

        user = secrets["JENKINS_USER"]
        token = secrets["JENKINS_TOKEN"]
        crumb = secrets["JENKINS_CRUMB"]
        self.jenkins = Jenkins(user, token, crumb)

        self.slack_read_token = secrets["SLACK_READ_TOKEN"]
        bot_token = secrets["SLACK_SEND_TOKEN"]
        app_token = secrets["SLACK_APP_TOKEN"]
        self.slack = Slack(bot_token, app_token)

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


def run_tom(interactive, secrets_dir):
    secrets = {}
    names = ["GITHUB_TOKEN", "JENKINS_CRUMB", "JENKINS_USER", "JENKINS_TOKEN", "SLACK_READ_TOKEN", "SLACK_SEND_TOKEN", "SLACK_APP_TOKEN"]
    for n in names:
        secrets[n] = get_var(n, secrets_dir)
    tom = Tom(secrets, interactive)
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

    if not var:
        sys.exit("Could not get {} from file or env".format(var))
    return var


def get_args():
    argparser = argparse.ArgumentParser(description='CFEngine Bot, Tom')
    argparser.add_argument(
        '--interactive', '-i', help='Ask first, shoot questions later', action="store_true")
    argparser.add_argument(
        '--continuous', '-c', help='Run in a loop, exits on error/failures', action="store_true")
    argparser.add_argument(
        '--secrets', '-s', help='Directory to read secrets', default="./", type=str)
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
    if args.continuous:
        while True:
            run_tom(args.interactive)
            print("Iteration complete, sleeping for 12 seconds")
            sleep(12)
    else:
        run_tom(args.interactive, args.secrets)


if __name__ == "__main__":
    main()  # Don't add any variables to global scope.
