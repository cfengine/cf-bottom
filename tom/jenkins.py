import logging as log
from time import sleep
import requests
from requests.auth import HTTPBasicAuth
from tom.utils import pretty


class Jenkins():
    def __init__(self, url, job, secrets):
        self.url = url

        user = secrets["JENKINS_USER"]
        token = secrets["JENKINS_TOKEN"]
        crumb = secrets["JENKINS_CRUMB"] if "JENKINS_CRUMB" in secrets else None

        self.user = user
        self.token = token
        self.crumb = crumb

        self.auth = HTTPBasicAuth(user, token)

        self.headers = {}
        if crumb:
            self.headers["Jenkins-Crumb"] = crumb

        self.job_name = job
        self.job_url = "{}job/{}/".format(self.url, self.job_name)
        self.trigger_url = "{}buildWithParameters/api/json".format(self.job_url)

    def post(self, path, data):
        r = requests.post(path, data=data, headers=self.headers, auth=self.auth)
        assert r.status_code >= 200 and r.status_code < 300
        print(r.headers)
        try:
            return r.headers, r.json()
        except:
            return r.headers, r.text

    def trigger(self, prs=None, branch="master", title=None):
        path = self.trigger_url
        params = {}
        repo_names = ",".join([k.lower() for k in prs])
        if prs:
            for repo in prs:
                param_name = repo.upper().replace("-", "_")
                assert " " not in param_name
                param_name = param_name + "_REV"
                params[param_name] = str(prs[repo])
        params["BASE_BRANCH"] = str(branch)
        if title is not None:
            description = "{} ({} {}@{})".format(title, "cf-bottom", repo_names, branch)
        else:
            description = "Unnamed build (cf-bottom)"
        params["BUILD_DESC"] = description
        return self.post(path, params)

    def wait_for_queue(self, url):
        log.debug("Queue URL: {}".format(url))
        queue_item = {}
        while "executable" not in queue_item:
            log.info("Waiting for jenkins build in queue")
            sleep(1)
            r = requests.get(url + "api/json")
            assert r.status_code >= 200 and r.status_code < 300
            queue_item = r.json()
        log.debug(pretty(queue_item))

        num = queue_item["executable"]["number"]
        url = queue_item["executable"]["url"]
        return num, url
