import os
import argparse
import logging as log

from tom.bot import Bot
from tom.reports import Reports
from tom.utils import read_json, user_error


def setup_bot(directory, interactive, data, reports):
    secrets = data["secrets_data"]
    del data["secrets_data"]
    return Bot(data, secrets, directory, interactive, reports)


def run_talk(directory, user, interactive):
    config = load_config(directory)
    assert len(config["bots"]) > 0
    for bot_data in config["bots"]:
        if bot_data["username"] == user:
            reports = Reports(directory)
            bot = setup_bot(directory, interactive, bot_data, reports)
            bot.talk()
            return
    user_error("Couldn't find config for bot '{}'".format(user))


def run_bot(directory, interactive, data, reports):
    bot = setup_bot(directory, interactive, data, reports)
    bot.run()


def load_config(directory):
    config = read_json(os.path.join(directory, "config.json"))
    assert config

    for bot_data in config["bots"]:
        secrets_path = bot_data["secrets"]
        if not secrets_path.startswith("/"):
            secrets_path = os.path.join(directory, secrets_path)

        bot_data["secrets_path"] = secrets_path
        bot_data["secrets_data"] = None

        if not os.path.isfile(secrets_path):
            continue

        bot_data["secrets_data"] = read_json(secrets_path)

    return config


def run_all_bots(directory, interactive):
    runs = 0
    config = load_config(directory)
    assert len(config["bots"]) > 0
    reports = Reports(directory)
    for bot_data in config["bots"]:
        secrets_data = bot_data["secrets_data"]
        if not secrets_data:
            log.warning(
                "Skipping bot '{}', secrets file '{}' not found".format(
                    bot_data["username"], bot_data["secrets_path"]
                )
            )
            continue

        run_bot(directory, interactive, bot_data, reports)
        runs += 1
    if runs <= 0:
        user_error("Did not complete any runs, check config")
    reports.dump()


def get_args():
    argparser = argparse.ArgumentParser(description="CFEngine Bot, Tom")
    argparser.add_argument(
        "--interactive",
        "-i",
        help=(
            "Assume user present at terminal: "
            + "in normal mode ask first, shoot questions later; "
            + "in talk mode - talk to the user, not to the server"
        ),
        action="store_true",
    )
    argparser.add_argument(
        "--directory",
        "-d",
        help="Directory to use for config, secrets and logs",
        default="./",
        type=str,
    )
    argparser.add_argument(
        "--talk-user",
        "-t",
        help="Run Tom in talk mode, when it reads Slack message from stdin",
        type=str,
    )
    argparser.add_argument("--log-level", "-l", help="Detail of log output", type=str)
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
    if args.talk_user:
        run_talk(args.directory, args.talk_user, args.interactive)
    else:
        run_all_bots(args.directory, args.interactive)


if __name__ == "__main__":
    main()  # Don't add any variables to global scope.
