import os
import sys
import json
import argparse
import requests
import random
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

trusted = [nick, vratislav, craig, ole, aleksei]

repos = {
    "cfengine/core": [ole, vratislav],
    "cfengine/enterprise": [ole, vratislav, craig],
    "cfengine/nova": [ole, vratislav, craig],
    "cfengine/masterfiles": [craig, nick],
    "cfengine/buildscripts": [craig, aleksei],
    "cfengine/documentation": [nick, craig],
    "cfengine/contrib": [nick],
    "cf-bottom/self": [ole, vratislav, tom]
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

    def trigger(self, prs=None, branch=None, title=None):
        path = self.trigger_url
        params = {}
        if prs:
            for repo in prs:
                param_name = repo.upper().replace("-", "_")
                assert " " not in param_name
                param_name = param_name + "_REV"
                params[param_name] = str(prs[repo])
        if branch is not None:
            params["BASE_BRANCH"] = str(branch)
        if title is not None:
            description = "{} ({})".format(title, "cf-bottom")
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
        return data

    def put(self, path, data):
        log.critical("PUT has not been implemented yet!")
        raise NotImplementedError

    def api_log(self, msg):
        log.debug("{}".format(msg))
        with open("api.log", "a") as f:
            f.write(msg + "\n")

    def post(self, path, data):
        self.api_log("POST {} {}".format(path, data))
        r = requests.post(path, headers=self.headers, json=data)
        log.debug("RESPONSE {}".format(r.status_code))
        assert r.status_code >= 200 and r.status_code < 300
        data = r.json()
        log.debug(pretty(data))
        return data

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
        if len(self.reviewers) > 1 and nick in self.reviewers:
            self.reviewers.remove(nick)
        self.reviewer = random.choice(self.reviewers)

        self.reviews = self.github.get(self.reviews_url)
        self.approvals = []
        for r in self.reviews:
            if r["state"] == "APPROVED":
                self.approvals.append(r["user"]["login"])

    def has_label(self, label_name):
        label_name = label_name.lower()
        return label_name in self.labels


class Tom():
    def __init__(self, secrets, interactive):
        github = secrets["GITHUB_TOKEN"]
        self.github = GitHub(github)

        user = secrets["JENKINS_USER"]
        token = secrets["JENKINS_TOKEN"]
        crumb = secrets["JENKINS_CRUMB"]
        self.jenkins = Jenkins(user, token, crumb)
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

        msg = []
        msg.append(str(comment))
        msg.append("Triger build for: {}".format(pr.title))
        msg.append("PRs: {}".format(prs))
        msg = "\n".join(msg)
        if not confirmation(msg):
            return

        headers, body = self.jenkins.trigger(prs, title=pr.title)

        queue_url = headers["Location"]

        num, url = self.jenkins.wait_for_queue(queue_url)

        print("Triggered build ({}): {}".format(num, url))
        self.comment_badge(pr, num, url)

    def handle_comments(self, pr):
        for comment in reversed(pr.comments):
            if comment.author == "cf-bottom":
                return
            if comment.author not in trusted:
                continue
            if "@cf-bottom" in comment:
                body = comment.body.lower()
                trigger_words = ["jenkins", "pipeline", "build"]
                for word in trigger_words:
                    if word.lower() in body:
                        self.trigger_build(pr, comment)
                        return

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


def run_tom(interactive):
    secrets = {}
    names = ["GITHUB_TOKEN", "JENKINS_CRUMB", "JENKINS_USER", "JENKINS_TOKEN"]
    for n in names:
        secrets[n] = get_var(n)
    tom = Tom(secrets, interactive)
    tom.run()


def get_var(name):
    var = None
    if name in os.environ:
        var = os.environ[name]
    else:
        try:
            with open(name, "r") as f:
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

    run_tom(args.interactive)


if __name__ == "__main__":
    main()  # Don't add any variables to global scope.
