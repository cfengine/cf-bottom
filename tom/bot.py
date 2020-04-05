import sys
import random
import json
import datetime
import logging as log
from copy import copy

from tom.github import GitHub, GitHubInterface, PR
from tom.jenkins import Jenkins
from tom.slack import Slack, CommandDispatcher
from tom.dependencies import UpdateChecker
from tom.changelog import ChangelogGenerator
from tom.tag import Tagger
from tom.utils import confirmation, pretty, email_sha256


class Bot():
    def __init__(self, config, secrets, directory, interactive):
        self.secrets = secrets
        self.directory = directory
        self.interactive = interactive

        self.bot_features = config["bot_features"]

        self.username = config["username"]
        self.orgs = config["orgs"]
        self.repo_maintainers = config["repos"]
        self.default_maintainers = config["reviewers"]
        self.trusted = config["trusted"]
        self.jenkins_repos = config["jenkins_repos"]
        banned_emails = config.get("banned_emails", {})
        self.banned_emails = [v for v in banned_emails.values()]

        self.jenkins = Jenkins(config["jenkins"], config["jenkins_job"], secrets, self.username)
        self.github = GitHub(secrets["GITHUB_TOKEN"], self.username, self.jenkins_repos)

        self.slack = Slack(
            read_token=secrets.get("SLACK_READ_TOKEN"),
            bot_token=secrets.get("SLACK_SEND_TOKEN"),
            app_token=secrets.get("SLACK_APP_TOKEN"),
            username=self.username,
            interactive=interactive)
        self.dispatcher = CommandDispatcher(self.slack)
        if 'create_pr_magic' in config["bot_features"]:
            self.github_interface = GitHubInterface(self.github, self.slack, self.dispatcher)
        if 'update_dependencies' in config["bot_features"]:
            self.updater = UpdateChecker(self.github, self.slack, self.dispatcher, 'Lex-2008')
        if 'generate_changelogs' in config["bot_features"]:
            self.changelogger = ChangelogGenerator(
                self.github, self.slack, self.dispatcher, 'Lex-2008')
        if 'tag_builds' in config["bot_features"]:
            self.tagger = Tagger(self.github, self.slack, self.dispatcher, 'Lex-2008')

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
        if pr.age < datetime.timedelta(days=1):
            log.info("This PR is less than a day old, I won't ping yet")
        elif self.username in pr.comments.users:
            log.info("I have already commented :)")
        elif len(pr.comments) > 0:
            log.info("There are already comments there, so I won't disturb")
        elif len(pr.requested_reviewers) > 0:
            log.info("Someone already assigned a reviewer, I won't disturb")
        elif len(pr.reviews) > 0:
            log.info("This PR has reviews already, so I'll leave it to you humans")
        elif pr.has_label("WIP") or "WIP" in pr.title.upper():
            log.info("This is a WIP PR, so I won't disturb")
        else:
            thanks = random.choice(["Thanks", "Thank you"])
            pull = random.choice(["PR", "pull request"])
            comment = "{thanks} for submitting a {pr}! Maybe @{user} can review this?".format(
                thanks=thanks, pr=pull, user=pr.reviewer)
            self.comment(pr, comment)

    def review(self, pr):
        tom = self.username
        log.info("Reviewing: {}".format(pr.title))

        if tom in pr.denials:
            log.info("I've already denied this PR")
            return

        log.debug("E-mails: {}".format(pr.emails))
        bad_emails = set()
        for email in pr.emails:
            hash = email_sha256(email)
            log.debug("{}: {}".format(email, hash))
            if email in self.banned_emails or hash in self.banned_emails:
                log.info("Found banned email: " + email)
                bad_emails.add(email)

        obfuscated = [f"{e[0]}***@{e[e.index('@')+1:]}" for e in bad_emails]
        bad_emails = ",".join(obfuscated)

        if bad_emails:
            body = f"Please use a company e-mail instead of {bad_emails}"
            event = "REQUEST_CHANGES"
            data = {"body": body, "event": event}
            self.post(pr.reviews_url, data)
            print("Denied PR: {}".format(pr.title))
            return

        if tom in pr.maintainers and tom not in [pr.denials + pr.approvals]:
            for person in pr.approvals:
                if person in pr.maintainers:
                    log.info("Approved by: " + str(pr.approvals))
                    body = "I trust @{}, approved!".format(person)
                    event = "APPROVE"
                    data = {"body": body, "event": event}
                    self.post(pr.reviews_url, data)
                    print("Approved PR: {}".format(pr.title))
                    return

    def comment_badge(self, pr, num, url, badge_text):
        badge_icon = "{url}/buildStatus/icon?job={job}&build={num}".format(
            url=self.jenkins.url, job=self.jenkins.job_name, num=num)
        badge_link = "{url}/job/{job}/{num}/".format(
            url=self.jenkins.url, job=self.jenkins.job_name, num=num)
        badge = "[![Build Status]({})]({})".format(badge_icon, badge_link)
        response = random.choice(["Alright", "Sure"])
        if badge_text:
            badge_text = "\n\n" + badge_text  # Under looks better
        buildcache = "http://buildcache.cfengine.com"
        packages = "{}/packages/testing-pr/jenkins-pr-pipeline-{}/".format(buildcache, num)
        new_comment = "{}, I triggered a build:\n\n{}{}\n\n**Jenkins:** {}\n\n**Packages:** {}".format(
            response, badge, badge_text, url, packages)
        self.comment(pr, new_comment)

    def trigger_build(self, pr, comment):
        prs = {}
        prs[pr.short_repo_name] = pr.number
        for repo_name in pr.merge_with:
            if repo_name not in prs:
                prs[repo_name] = pr.merge_with[repo_name]
        description = ""
        exotics = False
        if "exotic" in comment:
            exotics = True
            description = "(with exotics)"

        if self.interactive:
            msg = []
            msg.append(str(comment))
            msg.append("Triger build for: {}".format(pr.title))
            msg.append("PRs: {}".format(prs))
            msg.append("EXOTICS: {}".format(exotics))
            msg = "\n".join(msg)
            if not confirmation(msg):
                return

        headers, body = self.jenkins.trigger(prs, pr.base_branch, pr.title, exotics, comment.author)

        queue_url = headers["Location"]

        num, url = self.jenkins.wait_for_queue(queue_url)

        print("Triggered build ({}): {}".format(num, url))
        self.comment_badge(pr, num, url, description)

    def handle_mention(self, pr, comment):
        deny = "@{} : I'm sorry, I cannot do that. @olehermanse please help.".format(comment.author)
        if comment.author not in self.trusted:
            print("Denying mention from {}".format(comment.author))
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
            if comment.author == self.username:
                return
            if "@" + self.username in comment:
                self.handle_mention(pr, comment)

    def find_reviewers(self, pr):
        maintainers = self.default_maintainers
        if pr.repo in self.repo_maintainers:
            maintainers = self.repo_maintainers[pr.repo]

        pr.maintainers = maintainers
        pr.reviewers = copy(maintainers)
        if pr.author in pr.reviewers:
            pr.reviewers.remove(pr.author)
        if self.username in pr.reviewers:
            pr.reviewers.remove(self.username)
        if len(pr.reviewers) <= 0:
            pr.reviewers = self.default_maintainers
        pr.reviewer = random.choice(pr.reviewers)

    def handle_pr(self, pr):
        url = pr["url"].replace("https://api.github.com/repos/", "")
        log.info("Looking at: {} ({})".format(pr["title"], url))

        pr = PR(pr, self.github)
        self.find_reviewers(pr)
        if "ping_reviewer" in self.bot_features:
            self.ping_reviewer(pr)
        self.review(pr)
        self.handle_comments(pr)

    def run(self):
        self.repos = []
        if self.orgs:
            for org in self.orgs:
                self.repos += self.github.get("/orgs/{}/repos".format(org))

        self.repos = {repo["full_name"]: repo["url"] for repo in self.repos}
        for repo in self.repo_maintainers:
            self.repos[repo] = "/repos/" + repo

        self.pulls = []
        for repo, url in self.repos.items():
            log.info("Fetching pull requests for {}".format(repo))
            pulls = self.github.get(url + "/pulls")
            if pulls:
                self.pulls.extend(pulls)

        if self.pulls:
            log.info("Found {} open pull requests".format(len(self.pulls)))
        else:
            log.warning("Couldn't find any open pull requests!")

        errs = 0
        for pull in self.pulls:
            try:
                self.handle_pr(pull)
            except AssertionError:
                log.error("AssertionError encountered while handling '{}'".format(pull["title"]))
                errs += 1
        if (errs == 0):
            log.info("Tom successful")
        else:
            log.error("Tom encountered {} errors".format(errs))

    def talk(self):
        if not self.interactive:
            self.slack.parse_stdin(self.dispatcher)
            return

        print('Type Slack messages (do not prefix them with bot name)')
        print('Type "help" for list of commands')
        print('Type "quit" or "exit" when bored')
        prompt = '<@{}> '.format(self.username)
        self.slack.reply_to_user = 'con'
        while True:
            try:
                text = input(prompt)
            except EOFError:
                # Ctrl-D was pressed
                return
            if text.lower().strip() in ['quit', 'exit']:
                return
            self.dispatcher.parse_text(text)
