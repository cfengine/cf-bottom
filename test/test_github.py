from tom.github import GitHub

token = "test-github-token"
user_agent = "test-github-user-agent"
known_repos = ["cfengine/core", "cfengine/enterprise", "cfengine/masterfiles"]
github = GitHub(token, user_agent, known_repos)


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
