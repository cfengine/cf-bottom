import os
import datetime
import logging as log

from tom.utils import write_json

class Reports():
    def __init__(self, directory):
        self._prs = []
        self.directory = os.path.join(directory, "reports")

    def log_pr(self, pr):
        self._prs.append(pr)

    def dump(self):
        if not self._prs:
            log.info("Nothing to report - skipping dump")
            return
        os.makedirs("reports/", exist_ok=True)

        log.info("PRs for reports: " + str(len(self._prs)))
        open = []
        dependabot = []
        aged = []
        for pr in self._prs:
            data = {}
            data["url"] = pr.url
            data["title"] = pr.title
            data["created"] = str(pr.created)
            data["author"] = pr.author
            open.append(data)
            if datetime.datetime.now() - pr.created < datetime.timedelta(days=14):
                continue
            aged.append(data)
            if pr.author == "dependabot":
                dependabot.append(data)
        def save_to_file(prs, path):
            # Limit to prevent too big files for reporting
            # Need to adjust policy to not report whole file as 1 variable
            if len(prs) > 10:
                prs = prs[0:10]
            dictionary = {"count": len(prs), "open_prs": prs}
            write_json(dictionary, path)
        save_to_file(open, os.path.join(self.directory, "open_prs.json"))
        save_to_file(dependabot, os.path.join(self.directory, "dependabot_prs.json"))
        save_to_file(aged, os.path.join(self.directory, "aged_prs.json"))
