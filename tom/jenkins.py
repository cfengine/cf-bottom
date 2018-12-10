import logging as log
from time import sleep
import requests
from requests.auth import HTTPBasicAuth
from tom.utils import pretty


class Jenkins():
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

    def trigger(self, prs=None, branch="master", title=None, exotics=False, user=None):
        path = self.trigger_url
        params = {}
        branches = ["{}#{}".format(r, p) for r, p in prs.items()]
        branches.append(branch)
        branches = " ".join(branches)
        if prs:
            for repo in prs:
                param_name = repo.upper().replace("-", "_")
                assert " " not in param_name
                param_name = param_name + "_REV"
                params[param_name] = str(prs[repo])
        params["BASE_BRANCH"] = str(branch)
        if not user:
            user = self.username
        if exotics:
            params["RUN_ON_EXOTICS"] = True
        if title is not None:
            description = "{} @{} ({})".format(title, user, branches)
        else:
            description = "Unnamed build ({})".format(user)
        if exotics:
            description += " - WITH EXOTICS"
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
