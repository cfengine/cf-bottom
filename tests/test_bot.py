def test_trigger_build_system_test():
    github_requests, jenkins_requests = _trigger_build(
        repo="core",
        prs={"core": 23, "system-testing": 86},
        comment="@cf-bottom trigger",
    )

    jenkins_requests.post.assert_called_once_with(
        "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json",
        data={
            "BASE_BRANCH": "master",
            "CORE_REV": "23",
            "SYSTEM_TESTING_REV": "86",
            "BUILD_DESC": "Test PR Title @test-trusted-author (core#23 system-testing#86 master)",
        },
        headers={"Jenkins-Crumb": "test-jenkins-crumb"},
        auth=ANY,
    )
    github_requests.post.assert_called_once_with(
        "https://github.com/cfengine/core/pulls/23/comment_reference",
        headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
        json={
            "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
        },
    )


def test_trigger_build_basic():
    github_requests, jenkins_requests = _trigger_build(
        repo="core",
        prs={"core": 42, "nova": 43},
        comment="@cf-bottom build please",
        base_branch="3.15.x",
    )

    jenkins_requests.post.assert_called_once_with(
        "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json",
        data={
            "CORE_REV": "42",
            "NOVA_REV": "43",
            "BASE_BRANCH": "3.15.x",
            "BUILD_DESC": "Test PR Title @test-trusted-author (core#42 nova#43 3.15.x)",
        },
        headers={"Jenkins-Crumb": "test-jenkins-crumb"},
        auth=ANY,
    )

    github_requests.post.assert_called_once_with(
        "https://github.com/cfengine/core/pulls/42/comment_reference",
        headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
        json={
            "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
        },
    )


def test_exotics_build():
    github_requests, jenkins_requests = _trigger_build(
        repo="core",
        prs={"core": 42, "nova": 43},
        comment="@cf-bottom jenkins with exotics please",
    )
    jenkins_requests.post.assert_called_once_with(
        "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json",
        data={
            "CORE_REV": "42",
            "NOVA_REV": "43",
            "BASE_BRANCH": "master",
            "RUN_ON_EXOTICS": True,
            "BUILD_DESC": "Test PR Title @test-trusted-author (core#42 nova#43 master) - WITH EXOTICS",
        },
        headers={"Jenkins-Crumb": "test-jenkins-crumb"},
        auth=ANY,
    )
    github_requests.post.assert_called_once_with(
        "https://github.com/cfengine/core/pulls/42/comment_reference",
        headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
        json={
            "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n(with exotics)\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
        },
    )


def test_notest_build():
    github_requests, jenkins_requests = _trigger_build(
        repo="core",
        prs={"core": 42, "nova": 43},
        comment="@cf-bottom jenkins with no tests please",
    )
    jenkins_requests.post.assert_called_once_with(
        "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json",
        data={
            "CORE_REV": "42",
            "NOVA_REV": "43",
            "BASE_BRANCH": "master",
            "NO_TESTS": True,
            "BUILD_DESC": "Test PR Title @test-trusted-author (core#42 nova#43 master) [NO TESTS]",
        },
        headers={"Jenkins-Crumb": "test-jenkins-crumb"},
        auth=ANY,
    )
    github_requests.post.assert_called_once_with(
        "https://github.com/cfengine/core/pulls/42/comment_reference",
        headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
        json={
            "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n [NO TESTS]\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
        },
    )


def test_all_options_build():
    github_requests, jenkins_requests = _trigger_build(
        repo="documentation",
        prs={
            "core": 42,
            "nova": 43,
            "enterprise": 44,
            "masterfiles": 45,
            "buildscripts": 46,
            "documentation": 47,
            "mission-portal": 48,
            "libntech": 49,
            "documentation-generator": 50,
        },
        comment="@cf-bottom trigger jenkins build pipeline exotics no tests",
        base_branch="3.18",  # documentation doesn't use the .x suffix
    )
    # github comment response is really the same every time, so just make sure it was called
    # the actual message is covered in another test above
    github_requests.post.assert_called_once_with(
        "https://github.com/cfengine/documentation/pulls/47/comment_reference",
        headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
        json={
            "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=build-and-deploy-docs-3.18&build=22)](https://ci.cfengine.com//job/build-and-deploy-docs-3.18/22/)\n\n(with exotics) [NO TESTS]\n\n**Jenkins:** https://ci.cfengine.com/job/build-and-deploy-docs-3.18/22\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-build-and-deploy-docs-3.18-22/\n\n**Documentation:** http://buildcache.cfengine.com/packages/build-documentation-pr/jenkins-build-and-deploy-docs-3.18-22/output/_site/"
        },
    )
    jenkins_requests.post.assert_called_once_with(
        "https://ci.cfengine.com/job/build-and-deploy-docs-3.18/buildWithParameters/api/json",
        data={
            "RUN_ON_EXOTICS": True,
            "DOCS_BRANCH": "pr",
            "DOCS_REV": "47",
            "CORE_REV": "42",
            "NOVA_REV": "43",
            "ENTERPRISE_REV": "44",
            "MASTERFILES_REV": "45",
            "BUILDSCRIPTS_REV": "46",
            "MISSION_PORTAL_REV": "48",
            "LIBNTECH_REV": "49",
            "DOCS_GEN_REV": "50",
            "BASE_BRANCH": "3.18.x",
            "NO_TESTS": True,
            "BUILD_DESC": "Test PR Title @test-trusted-author (documentation#47 core#42 nova#43 enterprise#44 masterfiles#45 buildscripts#46 mission-portal#48 libntech#49 documentation-generator#50 3.18) - WITH EXOTICS [NO TESTS]",
        },
        headers={"Jenkins-Crumb": "test-jenkins-crumb"},
        auth=ANY,
    )


def test_fast_docs_build_318():
    github_requests, jenkins_requests = _trigger_build(
        repo="documentation",
        prs={"documentation": 42, "documentation-generator": 43},
        comment="@cf-bottom trigger please",
        base_branch="3.18",
    )
    github_requests.post.assert_called_once_with(
        "https://github.com/cfengine/documentation/pulls/42/comment_reference",
        headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
        json={
            "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=fast-build-and-deploy-docs-3.18&build=22)](https://ci.cfengine.com//job/fast-build-and-deploy-docs-3.18/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/fast-build-and-deploy-docs-3.18/22\n\n**Documentation:** http://buildcache.cfengine.com/packages/build-documentation-pr/jenkins-fast-build-and-deploy-docs-3.18-22/output/_site/"
        },
    )
    jenkins_requests.post.assert_called_once_with(
        "https://ci.cfengine.com/job/fast-build-and-deploy-docs-3.18/buildWithParameters/api/json",
        data={
            "DOCS_BRANCH": "pr",
            "DOCS_REV": "42",
            "DOCS_GEN_REV": "43",
            "BUILD_DESC": "Test PR Title @test-trusted-author (documentation#42 documentation-generator#43 3.18)",
        },
        headers={"Jenkins-Crumb": "test-jenkins-crumb"},
        auth=ANY,
    )


def test_slow_docs_build():
    github_requests, jenkins_requests = _trigger_build(
        repo="core",
        prs={"documentation": 42, "core": 43},
        comment="@cf-bottom build yeah?",
    )
    github_requests.post.assert_called_once_with(
        "https://github.com/cfengine/core/pulls/43/comment_reference",
        headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
        json={
            "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=build-and-deploy-docs-master&build=22)](https://ci.cfengine.com//job/build-and-deploy-docs-master/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/build-and-deploy-docs-master/22\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-build-and-deploy-docs-master-22/\n\n**Documentation:** http://buildcache.cfengine.com/packages/build-documentation-pr/jenkins-build-and-deploy-docs-master-22/output/_site/"
        },
    )
    jenkins_requests.post.assert_called_once_with(
        "https://ci.cfengine.com/job/build-and-deploy-docs-master/buildWithParameters/api/json",
        data={
            "CORE_REV": "43",
            "DOCS_REV": "42",
            "BASE_BRANCH": "master",
            "BUILD_DESC": "Test PR Title @test-trusted-author (core#43 documentation#42 master)",
            "DOCS_BRANCH": "pr",
            "CONFIGURATIONS_FILTER": "",
        },
        headers={"Jenkins-Crumb": "test-jenkins-crumb"},
        auth=ANY,
    )


from unittest.mock import MagicMock, patch, ANY
from tom.bot import Bot
from tom.jenkins import Jenkins
from tom.github import Comment

bot_username = "cf-bottom"
jenkins_base_url = "https://ci.cfengine.com/"
jenkins_default_job = "pr-pipeline"
trusted_author = "test-trusted-author"
test_github_token = "test-github-token"
test_jenkins_user = "test-jenkins-user"
test_jenkins_token = "test-jenkins-token"
test_jenkins_crumb = "test-jenkins-crumb"
# had to refactor a response_choices item in config to remove random response in github reply comment
config = {
    "response_choices": ["Predictably"],
    "username": bot_username,
    "jenkins": jenkins_base_url,
    "jenkins_job": jenkins_default_job,
    "trusted": [trusted_author],
    "secrets_data": {
        "GITHUB_TOKEN": test_github_token,
        "JENKINS_USER": test_jenkins_user,
        "JENKINS_TOKEN": test_jenkins_token,
        "JENKINS_CRUMB": test_jenkins_crumb,
    },
    "bot_features": {},
}
directory = ""
interactive = False
reports = []
bot = Bot(config, config["secrets_data"], directory, interactive, reports)
print("bot = {}".format(bot))


@patch("tom.jenkins.requests")
@patch("tom.github.requests")
def _trigger_build(
    github_requests, jenkins_requests, prs, comment, repo, base_branch="master"
):
    print("jenkins_requests = {}".format(jenkins_requests))
    print("prs = {}".format(prs))
    pr = MagicMock()
    pr.author = trusted_author
    pr.title = "Test PR Title"
    pr.repo = repo
    pr.short_repo_name = repo
    pr.number = prs[repo]
    pr.comments_url = (
        "https://github.com/cfengine/{}/pulls/{}/comment_reference".format(
            repo, pr.number
        )
    )
    pr.merge_with = prs
    pr.base_branch = base_branch
    comment = Comment({"body": comment, "user": {"login": trusted_author}})
    build_response = MagicMock()
    build_response.status_code = 200
    job_number = "22"

    def post_effect(path, data, headers, auth):
        jenkins_requests._path = path.replace("buildWithParameters/api/json", "")
        print("saving _path = {}".format(jenkins_requests._path))
        response = MagicMock(
            status_code=200,
        )
        response.json.return_value = {
            "executable": {
                "number": job_number,
                "url": "{}{}".format(jenkins_requests._path, job_number),
            }
        }
        return response

    def get_effect(path, headers, auth):
        print("saved _path is {}".format(jenkins_requests._path))
        response = MagicMock(
            status_code=200,
        )
        response.json.return_value = {
            "executable": {
                "number": job_number,
                "url": "{}{}".format(jenkins_requests._path, job_number),
            }
        }
        return response

    jenkins_requests.post.side_effect = post_effect

    jenkins_requests.get.side_effect = get_effect

    github_response = MagicMock()
    github_response.status_code = 200
    github_response.json.return_value = {}
    github_requests.post.return_value = github_response
    bot.trigger_build(pr, comment)
    print("github_requests: {}".format(github_requests.mock_calls))
    print("jenkins_requests: {}".format(jenkins_requests.mock_calls))
    return github_requests, jenkins_requests
