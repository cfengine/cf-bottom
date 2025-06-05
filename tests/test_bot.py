import os
import re
import datetime
from unittest import TestCase
from unittest.mock import patch, MagicMock, ANY

from tom.bot import Bot
from tom.github import Comment, PR
from tom.utils import read_json, write_json

bot_username = "cf-bottom"
jenkins_base_url = "https://ci.cfengine.com/"
jenkins_default_job = "pr-pipeline"
trusted_author = "test-trusted-author"
test_github_token = "test-github-token"
test_jenkins_user = "test-jenkins-user"
test_jenkins_token = "test-jenkins-token"
test_jenkins_crumb = "test-jenkins-crumb"

# Global config for bot initialization, used by _trigger_build
test_config = {
    "response_choices": ["Predictably"],
    "username": bot_username,
    "jenkins_url": jenkins_base_url,
    "jenkins_job": jenkins_default_job,
    "trusted_gh_users_to_start_jenkins_builds": [trusted_author],
    "secrets_data": {
        "GITHUB_TOKEN": test_github_token,
        "JENKINS_USER": test_jenkins_user,
        "JENKINS_TOKEN": test_jenkins_token,
        "JENKINS_CRUMB": test_jenkins_crumb,
    },
    "bot_features": {
        "ping_reviewer_for_new_pr_after_1_day",
        "ping_reviewer_dependabot",
        "check_commit_emails",
        "approve_prs",
        "trigger_jenkins_from_gh_comments",
        "report_open_prs",
    },
    "orgs": ["test-org"],
    "repo_maintainers": {"test-org/test-repo": ["test-maintainer"]},
    "repo_dependabot_maintainers": {"test-org/test-repo": "dependabot-maintainer"},
    "reviewers": ["default-reviewer"],
    "banned_emails": {"banned@example.com": "banned-hash"},
}


def _trigger_build(
    github_requests_mock, jenkins_requests_mock, prs_dict, comment_str, repo_short_name, base_branch="master"
):
    """
    Helper function to set up mocks and trigger the bot's build logic.
    `github_requests_mock` and `jenkins_requests_mock` are the patched `requests` modules.
    `prs_dict` is a dictionary mapping short repo names to PR numbers (e.g., {"core": 123}).
    `comment_str` is the full comment body string.
    `repo_short_name` is the short name of the main repository for the PR (e.g., "core").
    """
    # Create a fresh bot instance for each call
    current_bot = Bot(test_config, test_config["secrets_data"], "", False, [])

    pr_number = prs_dict[repo_short_name]
    
    pr = MagicMock(spec=PR)
    pr.author = trusted_author
    pr.title = "Test PR Title"
    pr.repo = f"cfengine/{repo_short_name}" # Full repo name
    pr.short_repo_name = repo_short_name
    pr.number = pr_number
    pr.comments_url = (
        f"https://github.com/cfengine/{repo_short_name}/pulls/{pr_number}/comment_reference"
    )
    # pr.merge_with should contain other PRs in the build, excluding the main one
    pr.merge_with = {k: v for k, v in prs_dict.items() if k != repo_short_name}
    pr.base_branch = base_branch
    pr.url = f"https://github.com/cfengine/{repo_short_name}/pull/{pr_number}"
    pr.has_label.return_value = False

    comment = Comment({"body": comment_str, "user": {"login": trusted_author}})

    job_number = "22" # Consistent job number for mocks

    def post_effect(path, data, headers, auth):
        # Store the job URL for the subsequent GET call
        jenkins_requests_mock._path = path.replace("buildWithParameters/api/json", "")
        response = MagicMock(status_code=200)
        response.headers = {"Location": f"{jenkins_requests_mock._path}queue/item/123/"} # Mock queue URL
        return response

    def get_effect(path, headers, auth):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "executable": {
                "number": job_number,
                "url": f"{jenkins_requests_mock._path}{job_number}/",
            }
        }
        return response

    jenkins_requests_mock.post.side_effect = post_effect
    jenkins_requests_mock.get.side_effect = get_effect

    github_response = MagicMock()
    github_response.status_code = 200
    github_response.json.return_value = {}
    github_requests_mock.post.return_value = github_response

    current_bot.trigger_build(pr, comment)

    return github_requests_mock, jenkins_requests_mock


class TestBot(TestCase):
    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_trigger_build_system_test(self, github_requests, jenkins_requests):
        github_requests, jenkins_requests = _trigger_build(
            github_requests,
            jenkins_requests,
            repo_short_name="core",
            prs_dict={"core": 5010, "nova": 1918, "system-testing": 445},
            comment_str="@cf-bottom trigger",
        )

        jenkins_requests.post.assert_called_once_with(
            "https://ci.cfengine.com/job/pr-pipeline/buildWithParameters/api/json",
            data={
                "BASE_BRANCH": "master",
                "CORE_REV": "5010",
                "NOVA_REV": "1918",
                "SYSTEM_TESTING_REV": "445",
                "BUILD_DESC": "Test PR Title @test-trusted-author (core#5010 nova#1918 system-testing#445 master)",
            },
            headers={"Jenkins-Crumb": "test-jenkins-crumb"},
            auth=ANY,
        )
        github_requests.post.assert_called_once_with(
            "https://github.com/cfengine/core/pulls/5010/comment_reference",
            headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
            json={
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22/\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
            },
        )


    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_trigger_build_basic(self, github_requests, jenkins_requests):
        github_requests, jenkins_requests = _trigger_build(
            github_requests,
            jenkins_requests,
            repo_short_name="core",
            prs_dict={"core": 42, "nova": 43},
            comment_str="@cf-bottom build please",
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
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22/\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
            },
        )


    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_exotics_build(self, github_requests, jenkins_requests):
        github_requests, jenkins_requests = _trigger_build(
            github_requests,
            jenkins_requests,
            repo_short_name="core",
            prs_dict={"core": 42, "nova": 43},
            comment_str="@cf-bottom jenkins with exotics please",
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
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n(with exotics)\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22/\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
            },
        )


    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_notest_build(self, github_requests, jenkins_requests):
        github_requests, jenkins_requests = _trigger_build(
            github_requests,
            jenkins_requests,
            repo_short_name="core",
            prs_dict={"core": 42, "nova": 43},
            comment_str="@cf-bottom jenkins with no tests please",
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
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n [NO TESTS]\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22/\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
            },
        )


    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_all_options_build(self, github_requests, jenkins_requests):
        github_requests, jenkins_requests = _trigger_build(
            github_requests,
            jenkins_requests,
            repo_short_name="documentation",
            prs_dict={
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
            comment_str="@cf-bottom trigger jenkins build pipeline exotics no tests",
            base_branch="3.18",  # documentation doesn't use the .x suffix
        )
        # github comment response is really the same every time, so just make sure it was called
        # the actual message is covered in another test above
        github_requests.post.assert_called_once_with(
            "https://github.com/cfengine/documentation/pulls/47/comment_reference",
            headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
            json={
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=build-and-deploy-docs-3.18&build=22)](https://ci.cfengine.com//job/build-and-deploy-docs-3.18/22/)\n\n(with exotics) [NO TESTS]\n\n**Jenkins:** https://ci.cfengine.com/job/build-and-deploy-docs-3.18/22/\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-build-and-deploy-docs-3.18-22/\n\n**Documentation:** http://buildcache.cfengine.com/packages/build-documentation-pr/jenkins-build-and-deploy-docs-3.18-22/output/_site/"
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


    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_fast_docs_build_318(self, github_requests, jenkins_requests):
        github_requests, jenkins_requests = _trigger_build(
            github_requests,
            jenkins_requests,
            repo_short_name="documentation",
            prs_dict={"documentation": 42, "documentation-generator": 43},
            comment_str="@cf-bottom trigger please",
            base_branch="3.18",
        )
        github_requests.post.assert_called_once_with(
            "https://github.com/cfengine/documentation/pulls/42/comment_reference",
            headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
            json={
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=fast-build-and-deploy-docs-3.18&build=22)](https://ci.cfengine.com//job/fast-build-and-deploy-docs-3.18/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/fast-build-and-deploy-docs-3.18/22/\n\n**Documentation:** http://buildcache.cfengine.com/packages/build-documentation-pr/jenkins-fast-build-and-deploy-docs-3.18-22/output/_site/"
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


    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_slow_docs_build(self, github_requests, jenkins_requests):
        github_requests, jenkins_requests = _trigger_build(
            github_requests,
            jenkins_requests,
            repo_short_name="core",
            prs_dict={"documentation": 42, "core": 43},
            comment_str="@cf-bottom build yeah?",
        )
        github_requests.post.assert_called_once_with(
            "https://github.com/cfengine/core/pulls/43/comment_reference",
            headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
            json={
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=build-and-deploy-docs-master&build=22)](https://ci.cfengine.com//job/build-and-deploy-docs-master/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/build-and-deploy-docs-master/22/\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-build-and-deploy-docs-master-22/\n\n**Documentation:** http://buildcache.cfengine.com/packages/build-documentation-pr/jenkins-build-and-deploy-docs-master-22/output/_site/"
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
                "CONFIGURATIONS_FILTER": "", # This is explicitly cleared for docs builds
            },
            headers={"Jenkins-Crumb": "test-jenkins-crumb"},
            auth=ANY,
        )


    @patch("tom.jenkins.requests")
    @patch("tom.github.requests")
    def test_label_configurations_filter_build(self, github_requests, jenkins_requests):
        # Define the PRs involved, with the main repo being 'core'
        prs_data = {"core": 123}
        
        # The comment body must include a semicolon at the end of the label expression
        # because the current regex in tom/bot.py expects it.
        label_expression = "contains('solaris') || label == 'PACKAGES_HUB_x86_64_linux_debian_7'"
        comment_body = f"@cf-bottom label {label_expression};"
        
        # Call the helper function that triggers the bot logic
        github_requests_mock, jenkins_requests_mock = _trigger_build(
            github_requests,
            jenkins_requests,
            prs_dict=prs_data,
            comment_str=comment_body,
            repo_short_name="core", # Main repo for this PR
            base_branch="master"
        )

        # Assert that jenkins_requests.post was called with the correct parameters
        jenkins_requests_mock.post.assert_called_once()
        
        call_args, call_kwargs = jenkins_requests_mock.post.call_args
        posted_params = call_kwargs.get('data')
        if posted_params is None and len(call_args) > 1:
            posted_params = call_args[1]

        self.assertIsNotNone(posted_params, "Jenkins post data was not found in call arguments.")
        self.assertIn("CONFIGURATIONS_FILTER", posted_params)
        self.assertEqual(posted_params["CONFIGURATIONS_FILTER"], label_expression)

        # Also check other expected parameters to ensure they are still present
        self.assertIn("CORE_REV", posted_params)
        self.assertEqual(posted_params["CORE_REV"], str(prs_data["core"]))
        
        expected_build_desc_prefix = f"Test PR Title @{trusted_author} (core#{prs_data['core']} master)"
        self.assertTrue(posted_params["BUILD_DESC"].startswith(expected_build_desc_prefix))
        
        self.assertEqual(posted_params["BASE_BRANCH"], "master")
        self.assertNotIn("RUN_ON_EXOTICS", posted_params)
        self.assertNotIn("NO_TESTS", posted_params)

        # Assert the GitHub comment as well
        github_requests_mock.post.assert_called_once_with(
            f"https://github.com/cfengine/core/pulls/{prs_data['core']}/comment_reference",
            headers={"Authorization": "token test-github-token", "User-Agent": "cf-bottom"},
            json={
                "body": "Predictably, I triggered a build:\n\n[![Build Status](https://ci.cfengine.com//buildStatus/icon?job=pr-pipeline&build=22)](https://ci.cfengine.com//job/pr-pipeline/22/)\n\n**Jenkins:** https://ci.cfengine.com/job/pr-pipeline/22/\n\n**Packages:** http://buildcache.cfengine.com/packages/testing-pr/jenkins-pr-pipeline-22/"
            },
        )
