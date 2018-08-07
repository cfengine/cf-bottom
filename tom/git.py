import os
import logging as log
import subprocess


class GitRepo():
    """Class responsible for working with locally checked-out repository"""

    def __init__(self, dirname, repo_name, upstream_name, my_name, checkout_branch=None):
        """Clones a remore repo to a directory (or freshens it if it's already
        checked out), configures it and optionally checks out a requested branch
        Args:
            dirname - name of directory in local filesystem where to clone the repo
            repo_name - name of repository (like 'core' or 'masterfiles')
            upstream_name - name of original owner of the repo (usually 'cfengine')
                We will pull from git@github.com:/upstream_name/repo_name
            my_name - name of github user where we will push and create PR from
                (usually 'cf-bottom')
                We will push to git@github.com:/my_name/repo_name
            checkout_branch - optional name of branch to checkout. If not provided,
                a branch from previous work might be left checked out
        """
        self.dirname = dirname
        self.repo_name = repo_name
        self.username = my_name
        self.usermail = my_name + '@cfengine.com'

        fetch_url = 'git@github.com:{}/{}.git'.format(upstream_name,repo_name)
        push_url = 'git@github.com:{}/{}.git'.format(my_name,repo_name)

        if os.path.exists(dirname):
            self.run_command('remote', 'set-url', 'origin', fetch_url)
            self.run_command('fetch')
        else:
            self.run_command('clone', '--no-checkout', fetch_url, dirname)
        self.run_command('remote', 'set-url', '--push', 'origin', push_url)
        if checkout_branch is not None:
            self.checkout(checkout_branch)

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
            self.run_command('reset', '--hard', 'origin/'+branch)

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
        """Pushes local branch to remote repo, optionally also setting upstream
        """
        if branch_name:
            self.run_command('push', '--set-upstream', 'origin', branch_name)
        else:
            self.run_command('push')
