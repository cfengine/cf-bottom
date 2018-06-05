import os
import sys
import json
import argparse
import requests
import random
from copy import copy

# Globals for convenience

nick = "nickanderson"
vratislav = "vpodzime"
craig = "craigcomstock"
ole = "olehermanse"
aleksei = "Lex-2008"

repos = {
    "core": [ole, vratislav],
    "enterprise": [ole, vratislav, craig],
    "nova": [ole, vratislav, craig],
    "masterfiles": [craig, nick],
    "buildscripts": [craig, aleksei],
    "documentation": [nick, craig],
    "contrib": [nick],
    "self": [ole, vratislav]
}

def get_reviewers(repo, exclude=None):
    assert exclude is None or type(exclude) is list

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
        path = self.path(path)
        if path in self.get_cache:
            return self.get_cache[path]
        r = requests.get(path, headers=self.headers)
        # print(r.text)
        # print(r.status_code)

        assert r.status_code >= 200 and r.status_code < 300
        data = r.json()
        # print(pretty(data))
        self.get_cache[path] = data
        return data

    def put(self, path, data):
        raise NotImplementedError

    def post(self, path, data):
        with open("api.log", "a") as f:
            f.write("POST {}\n{}".format(path, data))
        r = requests.post(path, headers=self.headers, json=data)
        # print(r.text)
        assert r.status_code >= 200 and r.status_code < 300
        data = r.json()
        # print(pretty(data))
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
        self.data = data
        self.github = github
        self.comments_url = data["comments_url"]
        self.author = data["user"]["login"]
        self.repo = data["base"]["repo"]["name"]
        self.title = data["title"]
        self.number = data["number"]

        self.labels = []
        if "labels" in data:
            self.labels = [label["name"].lower() for label in data["labels"]]

        self.comments = Comments(self.github.get(self.comments_url), github)

        self.reviewers = get_reviewers(self.repo, exclude=[self.author])
        if self.author in self.reviewers:
            self.reviewers.remove(self.author)
        if len(self.reviewers) > 1 and nick in self.reviewers:
            self.reviewers.remove(nick)
        self.reviewer = random.choice(self.reviewers)

    def has_label(self, label_name):
        label_name = label_name.lower()
        return label_name in self.labels


class Tom():
    def __init__(self, token, interactive):
        self.github = GitHub(token)
        self.interactive = interactive

    def comment(self, pr, message):
        path = pr.comments_url
        if self.interactive:
            print(pretty(pr.data))
            print("PR: {} ({}#{})".format(pr.title, pr.repo, pr.number))
            print("Comment: '{}'".format(message))
            choice = input("Accept? ")
            choice = choice.strip().lower()
            if choice != "y" and choice != "yes":
                return
        data = {"body": str(message)}
        self.github.post(path, data)

    def ping_reviewer(self, pr):
        if "cf-bottom" in pr.comments.users:
            print("I have already commented :)")
        elif len(pr.comments) > 0:
            print("There are already comments there, so I won't disturb")
        elif pr.has_label("WIP") or "WIP" in pr.title.upper():
            print("This is a WIP PR, so I won't disturb")
        else:
            # print(pretty(pr.data))
            thanks = random.choice(["Thanks", "Thank you"])
            pull = random.choice(["PR", "pull request"])
            comment = "{thanks} for submitting a {pr}! Maybe @{user} can review this?".format(
                thanks=thanks, pr=pull, user=pr.reviewer)
            self.comment(pr, comment)
        print("")

    def handle_pr(self, pr):
        print("Handling PR: {}".format(pr["url"]))
        # print(pretty(pr))
        pr = PR(pr, self.github)

        # TODO: Add conditions here for posting different types of comments
        # conditions can be update time, mentions of cf-bottom, etc.
        self.ping_reviewer(pr)

    def run(self):
        self.repos = self.github.get("/user/repos")
        self.repos += self.github.get("/orgs/cfengine/repos")

        self.pulls = []
        for repo in self.repos:
            print("Fetching pull requests for {}".format(repo["full_name"]))
            pulls = self.github.get(repo["url"] + "/pulls")
            if pulls:
                self.pulls.extend(pulls)

        if self.pulls:
            print("Found {} open pull requests".format(len(self.pulls)))
        else:
            print("Couldn't find any open pull requests!")

        print("")
        for pull in self.pulls:
            self.handle_pr(pull)


if __name__ == "__main__":
    args = get_args()
    token = None
    if "GITHUB_TOKEN" in os.environ:
        token = os.environ["GITHUB_TOKEN"]
    else:
        try:
            with open("GITHUB_TOKEN", "r") as f:
                token = f.read().strip()
        except (PermissionError, FileNotFoundError):
            pass

    if not token:
        sys.exit("Could not get GITHUB_TOKEN from file or env")

    tom = Tom(token, args.interactive)
    tom.run()
