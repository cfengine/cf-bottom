import os
from pathlib import Path
from tom.jenkins import Jenkins
from tom.main import load_config
from tom.utils import read_json


def test_target_baseline():
    data = {
        "prs": {"core": 42},
        "comment": {"author": "test-author"},
        "docs": False,
        "no_tests": True,
        "pr": {"base_branch": "master", "title": "test-pr-title"},
        "exotics": False,
    }
    r = trigger(data)
    print(r)
    assert (
        r["path"]
        == "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json"
    )
    expected = {
        "CORE_REV": "42",
        "BASE_BRANCH": "master",
        "NO_TESTS": True,
        "BUILD_DESC": "test-pr-title @test-author (core#42 master) [NO TESTS]",
    }
    assert expected == r["data"]


def trigger(data):
    os.environ["TOM"] = "PASSIVE"  # for testing, don't actually post
    # similar to tom/main.py run_all_bots
    directory = Path(os.path.realpath(__file__)).parent.parent.absolute()
    config = load_config(directory)
    #  print(config)
    user = "cf-bottom"
    for bot_data in config["bots"]:
        if bot_data["username"] == user:
            secrets_path = Path(os.path.realpath(__file__)).parent.absolute()
            #      print("secrets_path {}".format(secrets_path))
            bot_data["secrets_data"] = read_json(
                os.path.join(secrets_path, "cfengine-test-secrets.json")
            )
            #      print("bot_data:")
            #      print(bot_data)
            jenkins = Jenkins(
                bot_data["jenkins"],
                bot_data["jenkins_job"],
                bot_data["secrets_data"],
                "cf-bottom",
            )
            return jenkins.trigger(
                data["prs"],
                data["pr"]["base_branch"],
                data["pr"]["title"],
                data["exotics"],
                data["comment"]["author"],
                data["docs"],
                data["no_tests"],
            )
