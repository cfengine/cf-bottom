import sys
import random
import json
import logging as log

from tom.github import GitHub, GitHubInterface, PR
from tom.jenkins import Jenkins
from tom.slack import CommandDispatcher
from tom.utils import confirmation


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
        tom = "cf-bottom"
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
