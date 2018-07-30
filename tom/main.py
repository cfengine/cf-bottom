import os
import argparse
import logging as log

from tom.bot import Tom


def run_tom(interactive, secrets_dir, talk_mode):
    secrets = {}
    names = [
        "GITHUB_TOKEN", "JENKINS_CRUMB", "JENKINS_USER", "JENKINS_TOKEN", "SLACK_READ_TOKEN",
        "SLACK_SEND_TOKEN", "SLACK_APP_TOKEN"
    ]
    for n in names:
        secrets[n] = get_var(n, secrets_dir)
    tom = Tom(secrets, interactive)
    if talk_mode:
        tom.talk()
    else:
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
    return var


def get_args():
    argparser = argparse.ArgumentParser(description='CFEngine Bot, Tom')
    argparser.add_argument(
        '--interactive', '-i', help='Ask first, shoot questions later', action="store_true")
    argparser.add_argument(
        '--continuous', '-c', help='Run in a loop, exits on error/failures', action="store_true")
    argparser.add_argument(
        '--secrets', '-s', help='Directory to read secrets', default="./", type=str)
    argparser.add_argument(
        '--talk',
        '-t',
        help="Run Tom in talk mode, when it reads Slack message from stdin",
        action="store_true")
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
    log.getLogger("requests").setLevel(log.WARNING)
    log.getLogger("urllib3").setLevel(log.WARNING)
    if args.continuous:
        while True:
            run_tom(args.interactive, args.talk)
            print("Iteration complete, sleeping for 12 seconds")
            sleep(12)
    else:
        run_tom(args.interactive, args.secrets, args.talk)


if __name__ == "__main__":
    main()  # Don't add any variables to global scope.
