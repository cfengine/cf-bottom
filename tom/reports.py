import os
import datetime
import logging as log

from tom.utils import write_json


class Reports:
    def __init__(self, directory):
        self._prs = []
        self.directory = os.path.join(directory, "reports")

    def log_pr(self, pr):
        self._prs.append(pr)

    def dump(self):
        if not self._prs:
            log.info("Nothing to report - skipping dump")
            return
        os.makedirs(self.directory, exist_ok=True)

        log.info("PRs for reports: " + str(len(self._prs)))
        all = []
        dependabot = []
        old = []
        for pr in self._prs:
            data = {}
            data["url"] = pr.url
            data["title"] = pr.title
            data["created"] = str(pr.created)
            data["author"] = pr.author
            all.append(data)
            if datetime.datetime.now() - pr.created < datetime.timedelta(days=30):
                continue
            if pr.author == "dependabot[bot]" and not pr.url.startswith(
                "https://github.com/mendersoftware/mender-test-containers/pull/"
            ):
                # TODO - see: https://northerntech.atlassian.net/browse/SEC-881
                dependabot.append(data)
            old.append(data)

        def save_to_file(prs, path):
            count = len(prs)
            # if len(prs) > 4:
            #     prs = prs[0:4]
            dictionary = {"count": count, "prs": prs}
            write_json(dictionary, path, prettify=False)

        save_to_file(all, os.path.join(self.directory, "all_prs.json"))
        save_to_file(dependabot, os.path.join(self.directory, "dependabot_prs.json"))
        save_to_file(old, os.path.join(self.directory, "old_prs.json"))
