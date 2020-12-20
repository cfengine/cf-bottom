import re
import os
import requests
import subprocess
import datetime
import hashlib
import urllib.request
import logging as log
from tom.git import GitRepo
from tom.changelog import ChangelogGenerator

class TagException(Exception):
    """Base class for all exceptions in this file"""
    pass

class TagParsingException(TagException):
    """Exception that is risen if tag can't be split into parts"""
    pass


class TooManyArgumentsException(TagException):
    """Exception that is risen when there are too many arguments"""
    pass


class Tagger():
    """Class responsible for tagging.
    Currently it tags only for CFEngine
    """
    repos_root = '..'
    repo_names = ['core', 'nova', 'enterprise', 'mission-portal', 'buildscripts', 'masterfiles', 'ldap-api']

    def __init__(self, github, slack, dispatcher, username):
        self.github = github
        self.slack = slack
        self.username = username
        dispatcher.register_command(
            keyword='tag',
            callback=lambda branch: self.run(branch),
            parameter_name='branch',
            short_help='Add tag',
            long_help='Add tags and push them. Use just branch name to get ' +
            'suggested syntax, or add desired tag after a comma to do the ' +
            'tagging')
        dispatcher.register_command(
            keyword='untag',
            callback=lambda tag: self.untag(tag),
            parameter_name='tag',
            short_help='delete tag',
            long_help='delete tag from all repos')

    def get_current_tag(self, repo):
        return repo.run_command('describe', '--abbrev=0', capture_output=True).stdout.rstrip()

    def get_next_build_tag(self, old_tag, branch):
        if 'build' in old_tag:
            # 3.15.0-build2 -> 3.15.0-build3
            m = re.match('^(.*build)([0-9]+)$', old_tag)
            if m:
                # print('[%s] => [%s] + [%s]'%(old_tag, m.group(1), m.group(2)))
                return m.group(1) + str(int(m.group(2))+1)
            else:
                raise TagParsingException('Could not split tag [%s] into parts' % old_tag)
        else:
            # 3.15.0 -> 3.16.0-build1 or 3.15.1-build1, depending on branch
            # But first, strip release number from version
            # 3.12.5-2 -> 3.12.5
            old_tag = re.sub('-[0-9]+','',old_tag)
            next_version = ChangelogGenerator.get_next_version(old_tag, branch)
            return next_version + '-build1'

    def get_next_final_tag(self, old_tag, branch):
        if 'build' in old_tag:
            # 3.15.0-build2 -> 3.15.0
            return re.sub('-build.*', '', old_tag)
        else:
            # 3.15.0 -> None
            return None

    def init_repos(self, checkout_branch, checkout_tag):
        repos = (GitRepo(
                    dirname=os.path.join(self.repos_root, name),
                    repo_name=name,
                    upstream_name='cfengine',
                    my_name=self.username,
                    checkout_branch=checkout_branch,
                    checkout_tag=checkout_tag)
                 for name in self.repo_names)
        return repos

    def init_core(self, branch):
        name = 'core'
        return GitRepo(
                    dirname=os.path.join(self.repos_root, name),
                    repo_name=name,
                    upstream_name='cfengine',
                    my_name=self.username,
                    checkout_branch=branch)

    def suggest(self, branch):
        core = self.init_core(branch)
        current_tag = self.get_current_tag(core)
        next_build_tag = self.get_next_build_tag(current_tag, branch)
        self.slack.reply("to add *build* tag, say (%s will be created at the tip of %s branch):\ntag: %s,%s" %
                (next_build_tag, branch, branch, next_build_tag))
        next_final_tag = self.get_next_final_tag(current_tag, branch)
        if next_final_tag:
            self.slack.reply("to add *final* tag, say (%s will be created at existing %s tag):\ntag: %s,%s,%s" %
                    (next_final_tag, current_tag, branch, current_tag, next_final_tag))

    def add_tag(self, branch, tag, checkout_branch=None, checkout_tag=None):
        repos = self.init_repos(checkout_branch, checkout_tag)
        message = 'CFEngine %s' % tag.replace('-build', ' ')
        for repo in repos:
            repo.run_command('tag', '-s', '-a', tag, '-m', message)
            repo.push(tag, 'upstream')

    def run(self, args):
        if ',' in args:
            args = args.split(',')
        else:
            args = [args]
        if len(args) == 1:
            branch = args[0]
            self.suggest(branch)
        elif len(args) == 2:
            [branch, tag] = args
            self.add_tag(branch, tag, checkout_branch=branch)
        elif len(args) == 3:
            [branch, base_tag, tag] = args
            self.add_tag(branch, tag, checkout_tag=base_tag)
        else:
            raise TooManyArgumentsException('received %d arguments, expected max 3' % len(args))

    def untag(self, tag):
        repos = self.init_repos(None, None)
        for repo in repos:
            try:
                repo.run_command('tag', '-d', tag)
            except:
                pass
            # repo.push(tag)
