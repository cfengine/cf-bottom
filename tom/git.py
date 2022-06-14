import os
import logging as log
import subprocess


class GitException(Exception):
    """Base class for all exceptions in this file"""

    pass


class WrongArgumentsException(GitException):
    """Exception that is risen when incorrect arguments were passed"""

    pass


class GitRepo:
    """Class responsible for working with locally checked-out repository"""

    def __init__(
        self,
        dirname,
        repo_name,
        upstream_name,
        my_name,
        checkout_branch=None,
        checkout_tag=None,
    ):
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
            checkout_tag - same for tag.
        """
        self.dirname = dirname
        self.repo_name = repo_name
        self.username = my_name  # TODO: this should be github username of current user

        upstream_url = "git@github.com:{}/{}.git".format(upstream_name, repo_name)
        origin_url = "git@github.com:{}/{}.git".format(my_name, repo_name)

        if not os.path.exists(dirname):
            self.run_command("clone", "--no-checkout", origin_url, dirname)
        upstream_add_command_result = self.run_command(
            "remote", "add", "upstream", upstream_url, check=False
        )
        if upstream_add_command_result.returncode != 0:
            # Assume that we failed to add remote called 'upstream' because it was
            # already added. In this case, we should succeed in setting its url.
            self.run_command("remote", "set-url", "upstream", upstream_url)
        if checkout_branch is not None:
            self.checkout(checkout_branch)
        if checkout_tag is not None:
            self.checkout(checkout_tag, tag=True)

    def run_command(self, *command, **kwargs):
        """Runs a git command against git repo.
        Syntaxically this function tries to be as close to subprocess.run
        as possible, just adding 'git' with some extra parameters in the beginning
        """
        git_command = [
            "git",
            "-C",
            self.dirname,
            "-c",
            "push.default=simple",
            "-c",
            "checkout.defaultRemote=upstream",
            "-c",
            "advice.detachedHead=false",
        ]
        git_command.extend(command)
        if "check" not in kwargs:
            kwargs["check"] = True
        if "capture_output" in kwargs:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.PIPE
            del kwargs["capture_output"]
        if command[0] == "clone":
            # we can't `cd` to target folder when it does not exist yet,
            # so delete `-C self.dirname` arguments from git command line
            del git_command[1]
            del git_command[1]
        kwargs["universal_newlines"] = True
        log.debug("running command: {}".format(" ".join(git_command)))
        return subprocess.run(git_command, **kwargs)

    def checkout(self, branch=None, tag=None, remote="upstream", new=False):
        """Checkout given branch or tag, optionally creating branch.
        Note that it's an error to create-and-checkout branch which already exists.
        Also, it's not supported to create tags.
        """
        # parse args
        if not branch and not tag:
            raise WrongArgumentsException(
                "only one of `branch`, `tag` arguments can be passed to `checkout` function"
            )
        ref = branch or tag
        if not ref:
            raise WrongArgumentsException(
                "one of `branch`, `tag` arguments must be passed to `checkout` function"
            )
        if tag and new:
            raise WrongArgumentsException("this is not the way to create tags")

        if new:
            # just create new branch
            self.run_command("checkout", "-b", branch)
        else:
            # first, ensure that we're aware of target ref
            self.run_command("fetch", remote, ref)
            # switch to the branch
            if branch:
                self.run_command("checkout", branch)
            # ensure we're on the tip of ref
            self.run_command("reset", "--hard", "FETCH_HEAD")

    def get_file(self, path):
        """Returns contents of a file as a single string"""
        with open(self.dirname + "/" + path) as f:
            return f.read()

    def put_file(self, path, data, add=True):
        """Overwrites file with data, optionally running `git add {path}` afterwards"""
        with open(self.dirname + "/" + path, "w") as f:
            f.write(data)
        if add:
            self.run_command("add", path)

    def commit(self, message):
        """Creates commit with message"""
        self.run_command("commit", "-m", message, "--allow-empty")

    def push(self, ref=None, remote="origin"):
        """Pushes local branch or tag to remote repo, optionally also setting it as upstream"""
        if ref:
            self.run_command("push", remote, ref)
        else:
            self.run_command("push", remote)
