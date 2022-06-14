import copy
import os
from pathlib import Path
from tom.jenkins import Jenkins
from tom.main import load_config
from tom.utils import read_json


# baseline data, mangle for different cases
data = {
    "prs": {"core": 42},
    "comment": {"author": "test-author"},
    "docs": False,
    "no_tests": True,
    "pr": {"base_branch": "master", "title": "test-pr-title"},
    "exotics": False,
}


def test_docs_build():
    _data = copy.deepcopy(data)
    _data["docs"] = True
    (path, params) = build_path_and_params(_data)
    print(params)
    assert (
        path == "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json"
    )
    expected = {
        "CORE_REV": "42",
        "BASE_BRANCH": "master",
        "NO_TESTS": True,
        "BUILD_DOCS": True,
        "BUILD_DESC": "test-pr-title @test-author (core#42 master) [NO TESTS]",
        "DOCS_BRANCH": "pr",
        "DOCS_GEN_REV": "master",
        "DOCS_REV": "master",
        "NO_DEPLOYMENT_TESTS": True,
        "NO_FR_TESTS": True,
        "NO_STATIC_CHECKS": True,
        "CONFIGURATIONS_FILTER": 'label == "PACKAGES_HUB_x86_64_linux_ubuntu_16"',
    }
    assert expected == params


def test_default_build():
    print(data)
    (path, params) = build_path_and_params(data)
    assert (
        path == "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json"
    )
    expected = {
        "CORE_REV": "42",
        "BASE_BRANCH": "master",
        "NO_TESTS": True,
        "BUILD_DESC": "test-pr-title @test-author (core#42 master) [NO TESTS]",
    }
    assert expected == params


def build_path_and_params(data):
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
            return jenkins.build_path_and_params(
                data["prs"],
                data["pr"]["base_branch"],
                data["pr"]["title"],
                data["exotics"],
                data["comment"]["author"],
                data["docs"],
                data["no_tests"],
            )
