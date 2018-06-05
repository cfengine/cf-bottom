import os
import sys
import json
import argparse
import requests
import random
import logging as log
from copy import copy

# Global constants for convenience

nick = "nickanderson"
vratislav = "vpodzime"
craig = "craigcomstock"
ole = "olehermanse"
aleksei = "Lex-2008"
tom = "cf-bottom"

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


def get_args():
    argparser = argparse.ArgumentParser(description='CFEngine Bot, Tom')
    argparser.add_argument(
        '--interactive', '-i', help='Ask first, shoot questions later', action="store_true")
    argparser.add_argument('--log-level', '-l', help="Detail of log output", type=str)
    args = argparser.parse_args()

    return args


def pretty(data):
    return json.dumps(data, indent=2)


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


class Comments():
    def __init__(self, data, github):
        self.data = data
        self.github = github

        comments = data
        self.users = [comment["user"]["login"] for comment in comments]
        self.bodies = [comment["body"] for comment in comments]

    def __len__(self):
        return len(self.data)


class PR():
    def __init__(self, data, github):
        self.data = data  # JSON dict from GitHub API
        self.github = github  # GitHub object with http methods and credentials

        self.comments_url = data["comments_url"]  # POST comments to this URL
        self.author = data["user"]["login"]  # PR Author / Submitter
        self.repo = data["base"]["repo"]["full_name"]  # cfengine/core

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
    def __init__(self, token, interactive):
        self.github = GitHub(token)
        self.interactive = interactive

    def post(self, path, data, msg=None):
        if self.interactive:
            print("I'd like to POST something")
            if msg:
                print(msg)
            print("Path: {}".format(path))
            print("Data: {}".format(data))
            choice = input("Accept? ")
            choice = choice.strip().lower()
            if choice != "y" and choice != "yes":
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

    def handle_pr(self, pr):
        url = pr["url"].replace("https://api.github.com/repos/", "")
        log.info("Looking at: {} ({})".format(pr["title"], url))
        pr = PR(pr, self.github)

        self.ping_reviewer(pr)
        self.review(pr)

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


def run_tom(token, interactive):
    tom = Tom(token, interactive)
    tom.run()


def get_token():
    token = None
    if "GITHUB_TOKEN" in os.environ:
        token = os.environ["GITHUB_TOKEN"]
    else:
        try:
            with open("GITHUB_TOKEN", "r") as f:
                token = f.read().strip()
        except (PermissionError, FileNotFoundError):
            pass
    return token


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

    token = get_token()
    if not token:
        sys.exit("Could not get GITHUB_TOKEN from file or env")
    run_tom(token, args.interactive)


if __name__ == "__main__":
    main()  # Don't add any variables to global scope.
