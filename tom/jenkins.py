import logging as log
from time import sleep
import requests
from requests.auth import HTTPBasicAuth
from tom.utils import pretty
import os
from typing import Dict


class Jenkins:
    def __init__(self, url, job, secrets, username):
        self.url = url

        user = secrets["JENKINS_USER"]
        token = secrets["JENKINS_TOKEN"]
        crumb = secrets["JENKINS_CRUMB"] if "JENKINS_CRUMB" in secrets else None

        self.user = user
        self.token = token
        self.crumb = crumb
        self.username = username

        self.auth = HTTPBasicAuth(user, token)

        self.headers = {}
        if crumb:
            self.headers["Jenkins-Crumb"] = crumb

        self.job_name = job
        self.job_url = "{}job/{}/".format(self.url, self.job_name)
        self.trigger_url = "{}buildWithParameters/api/json".format(self.job_url)

    def post(self, path, data):
        if os.getenv("TOM") == "PASSIVE":
            print("Would post: " + path)
            return None
        r = requests.post(path, data=data, headers=self.headers, auth=self.auth)
        if not (200 <= r.status_code < 300):
            log.error("Unexpected HTTP response from Jenkins: {}".format(r.status_code))
            log.error(str(r.headers))
            log.error(str(r.text))
            raise AssertionError("HTTP response {} from Jenkins".format(r.status_code))

        try:
            return r.headers, r.json()
        except:
            return r.headers, r.text

    def trigger(
        self,
        prs: Dict[str, int] = None,
        branch="master",
        title=None,
        exotics=False,
        user=None,
        docs=False,
        no_tests=False,
    ):
        params = {}
        need_slow_build = any(
            repo
            for repo in prs.keys()
            if repo in ["core", "enterprise", "nova", "masterfiles"]
        )
        job = "pr-pipeline"
        if docs:
            if need_slow_build:
                job = "build-and-deploy-docs-{}".format(branch)
                no_tests = True  # but allow for override if specified
            else:
                job = "fast-build-and-deploy-docs-{}".format(branch)
        else:
            if "documentation" in prs.keys():
                job = "build-and-deploy-docs-{}".format(branch)
                no_tests = False
                # clear configurations filter out so all default packages are generated and tested
                params["CONFIGURATIONS_FILTER"] = ""
        path = "{}job/{}/buildWithParameters/api/json".format(self.url, job)
        branches = ["{}#{}".format(r, p) for r, p in prs.items()]
        branches.append(branch)
        branches = " ".join(branches)
        if not user:
            user = self.username
        if exotics:
            params["RUN_ON_EXOTICS"] = True
        if title is not None:
            description = "{} @{} ({})".format(title, user, branches)
        else:
            description = "Unnamed build ({})".format(user)
        # both build-and-deploy-docs types (fast and regular) can use "pr" as the DOCS_BRANCH/BRANCH
        # this translates to a docs URL of http://buildcache.cfengine.com/packages/build-documentation-pr/jenkins-pr-pipeline-52/output/_site/
        # which includes after build-documentation-pr folder, a folder for the specific pipeline build
        if "/build-and-deploy-docs" in path:
            params["DOCS_BRANCH"] = "pr"
        if "fast-build-and-deploy-docs" in path:
            params["BRANCH"] = "pr"
        repos_accepted = [
            "core",
            "enterprise",
            "nova",
            "masterfiles",
            "documentation",
            "documentation-generator",
        ]
        if "fast-build-and-deploy-docs" not in path:
            repos_accepted.extend(
                [
                    "libntech",
                    "buildscripts",
                    "mission-portal",
                    "ldap",
                    "mender-qa",
                ]
            )
            if docs:
                params["BASE_BRANCH"] = "{}.x".format(branch)
            else:
                params["BASE_BRANCH"] = str(branch)
            if exotics:
                description += " - WITH EXOTICS"
            if no_tests:
                params["NO_TESTS"] = True
                description += " [NO TESTS]"
        if prs:
            for repo in (r for r in prs.keys() if r in repos_accepted):
                param_name = repo.upper().replace("-", "_")
                assert " " not in param_name
                param_name = param_name + "_REV"
                param_name = param_name.replace("DOCUMENTATION", "DOCS")
                param_name = param_name.replace("GENERATOR", "GEN")
                params[param_name] = str(prs[repo])
        params["BUILD_DESC"] = description
        return self.post(path, params)

    def wait_for_queue(self, url):
        log.debug("Queue URL: {}".format(url))
        queue_item = {}
        while "executable" not in queue_item:
            log.info("Waiting for jenkins build in queue")
            sleep(1)
            r = requests.get(url + "api/json", headers=self.headers, auth=self.auth)
            assert r.status_code >= 200 and r.status_code < 300
            queue_item = r.json()
        log.debug(pretty(queue_item))

        num = queue_item["executable"]["number"]
        url = queue_item["executable"]["url"]
        return num, url
