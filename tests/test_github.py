import os
from tom.github import GitHub
from tom.github import PR
from tom.utils import read_json

top_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
config = read_json(os.path.join(top_dir, "config.json"))
bot = config["bots"][0]

github = GitHub("test-token", bot["username"], bot["jenkins_repos"])


def test_PR():
    data = {
        "comments_url": "https://github.com/test-comments-url",
        "user": {
            "login": "test-github-login",
        },
        "base": {
            "repo": {"full_name": "test-github-full-name", "name": "test-github-name"},
            "ref": "test-github-ref",
            "user": {"login": "test-base-user-login"},
        },
        "title": "test-github-title",
        "number": "test-github-number",
        "url": "https://github.com/test-url",
        "html_url": "https://github.com/test-html-url",
        "commits_url": "https://github.com/test-commits-url",
        "requested_reviewers": [],
        "created_at": "2022-01-01T00:00:00Z",
        "body": """
Ticket: ENT-9037
Changelog: title

merge together:
cfengine/core#5010
cfengine/nova#1918
#1106
cfengine/system-testing#445
""",
    }
    pr = PR(data, github)
    assert pr.merge_with == {"core": 5010, "nova": 1918, "system-testing": 445}


def test_github():
    assert github


def test_path():
    assert github.path("/foo") == "https://api.github.com/foo"
    assert github.path("https://foo.bar") == "https://foo.bar"


def test_repo_path():
    assert github.repo_path("test-owner", "test-repo") == "/repos/test-owner/test-repo"


def test_comment_path():
    assert (
        github.comment_path("test-owner", "test-repo", "test-issue")
        == "/repos/test-owner/test-repo/issues/test-issue/comments"
    )
