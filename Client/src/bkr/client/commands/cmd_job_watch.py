# -*- coding: utf-8 -*-


from bkr.client import BeakerCommand
from optparse import OptionValueError
from bkr.client.task_watcher import *

class Job_Watch(BeakerCommand):
    """Watch Jobs/Recipes"""
    enabled = True

    def options(self):
        self.parser.usage = "%%prog %s" % self.normalized_name


    def run(self, *args, **kwargs):
        username = kwargs.pop("username", None)
        password = kwargs.pop("password", None)

        self.set_hub(username, password)
        TaskWatcher.watch_tasks(self.hub, args)
        for task in args:
            print self.hub.taskactions.to_xml(task)
