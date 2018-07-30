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
        """Pushes local branch to remote repo"""
        if branch_name:
            self.run_command('push', '--set-upstream', 'origin', branch_name)
        else:
            self.run_command('push')
