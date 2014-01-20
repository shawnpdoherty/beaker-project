
import os, os.path
import time
from turbogears.database import session
from bkr.common.helpers import makedirs_ignore
from bkr.labcontroller.config import get_conf
from bkr.labcontroller.proxy import WatchFile
from bkr.server.model import LogRecipe, TaskResult
from bkr.inttest import data_setup
from bkr.inttest.assertions import wait_for_condition
from bkr.inttest.labcontroller import LabControllerTestCase

class WatchdogConsoleLogTest(LabControllerTestCase):

    @classmethod
    def setUpClass(cls):
        makedirs_ignore(get_conf().get('CONSOLE_LOGS'), 0755)

    def setUp(self):
        with session.begin():
            self.system = data_setup.create_system(lab_controller=self.get_lc())
            self.recipe = data_setup.create_recipe()
            data_setup.create_job_for_recipes([self.recipe])
            data_setup.mark_recipe_running(self.recipe, system=self.system)
        self.console_log = os.path.join(get_conf().get('CONSOLE_LOGS'), self.system.fqdn)
        self.cached_console_log = os.path.join(get_conf().get('CACHEPATH'), 'recipes',
                str(self.recipe.id // 1000) + '+', str(self.recipe.id), 'console.log')

    def assert_panic_detected(self, message):
        with session.begin():
            self.assertEquals(len(self.recipe.tasks[0].results), 1)
            self.assertEquals(self.recipe.tasks[0].results[0].result,
                    TaskResult.panic)
            self.assertEquals(self.recipe.tasks[0].results[0].log,
                    message)

    def check_console_log_registered(self):
        with session.begin():
            return LogRecipe.query.filter_by(parent=self.recipe,
                    filename=u'console.log').count() == 1

    def check_cached_log_contents(self, expected):
        return open(self.cached_console_log, 'r').read() == expected

    def test_stores_console_log(self):
        first_line = 'Here is the first line of the log file.\n'
        open(self.console_log, 'w').write(first_line)
        wait_for_condition(self.check_console_log_registered)
        wait_for_condition(lambda: self.check_cached_log_contents(first_line))

        second_line = 'Here is the second line of the log file. FNORD FNORD FNORD\n'
        open(self.console_log, 'a').write(second_line)
        wait_for_condition(lambda: self.check_cached_log_contents(
                first_line + second_line))

    def test_panic_not_doubly_detected(self):
        # Write a panic string to the console log and wait for panic.
        open(self.console_log, 'w').write('Oops\n')
        wait_for_condition(self.check_console_log_registered)
        wait_for_condition(lambda: self.check_cached_log_contents('Oops\n'))
        self.assert_panic_detected(u'Oops')

        # Now check our kill_time
        session.expire_all()
        with session.begin():
            kill_time1 = self.recipe.watchdog.kill_time

        # Add another panic entry
        open(self.console_log, 'a+').write('Oops\n')
        wait_for_condition(lambda: self.check_cached_log_contents('Oops\nOops\n'))

        session.expire_all()
        with session.begin():
            # Ensure that there are no new panic results
            self.assertEquals(len(self.recipe.tasks[0].results), 1)
            # Ensure that our kill time has not been extended again!
            kill_time2 = self.recipe.watchdog.kill_time
        self.assertEquals(kill_time1, kill_time2)

    # https://bugzilla.redhat.com/show_bug.cgi?id=975486
    def test_panic_across_chunk_boundaries_is_detected(self):
        # Write some junk followed by a panic string. The panic string will be 
        # split across the chunk boundary.
        junk = 'z' * (WatchFile.blocksize - 10) + '\n'
        panic = 'Kernel panic - not syncing: Fatal exception in interrupt\n'
        with open(self.console_log, 'w') as f:
            f.write(junk + panic)
        wait_for_condition(self.check_console_log_registered)
        wait_for_condition(lambda: self.check_cached_log_contents(junk + panic))
        self.assert_panic_detected(u'Kernel panic')

    def test_incomplete_lines_not_buffered_forever(self):
        # The panic detection is only applied to complete lines (terminated 
        # with \n) but if for some reason we get a huge amount of output with 
        # no newlines we need to give up at some point and check the incomplete 
        # line. Otherwise in pathological cases we will end up consuming large 
        # amounts of memory.
        # The actual breakpoint used in the code (2*blocksize) is arbitrary, 
        # not chosen for any particularly good reason.
        long_panic_line = 'z' * (ConsoleWatchFile.blocksize - 10) + \
                'Kernel panic - not syncing: Fatal exception in interrupt ' + \
                'y' * (ConsoleWatchFile.blocksize + 100)
        with open(self.console_log, 'w') as f:
            f.write(long_panic_line)
        wait_for_condition(self.check_console_log_registered)
        wait_for_condition(lambda: self.check_cached_log_contents(long_panic_line))
        self.assert_panic_detected(u'Kernel panic')

    # https://bugzilla.redhat.com/show_bug.cgi?id=962901
    def test_console_log_not_recreated_after_removed(self):
        # The scenario for this bug is:
        # 1. beaker-watchdog writes the console log
        # 2. recipe finishes (but beaker-watchdog hasn't noticed yet)
        # 3. beaker-transfer tranfers the logs and removes the local copies
        # 4. beaker-watchdog writes more to the end of the console log (in the 
        # process re-registering the log file, and leaving the start of the 
        # file filled with zeroes)
        # 5. beaker-transfer tranfers the logs again
        # This test checks that step 4 is prevented -- the console log updates 
        # are silently discarded instead.

        # Step 1: beaker-watchdog writes the console log
        existing_data = 'Existing data\n'
        open(self.console_log, 'w').write(existing_data)
        wait_for_condition(self.check_console_log_registered)
        wait_for_condition(lambda: self.check_cached_log_contents(existing_data))

        # Step 2: the recipe "finishes"
        # Don't actually mark it as finished in the database though, to ensure 
        # the watchdog keeps monitoring the console log.

        # Step 3: beaker-transfer tranfers the logs and removes the local copies
        with session.begin():
            LogRecipe.query.filter_by(parent=self.recipe,
                    filename=u'console.log').one().server = u'http://elsewhere'
        os.remove(self.cached_console_log)

        # Step 4: beaker-watchdog tries to write more to the end of the console log
        open(self.console_log, 'a').write(
                'More console output, after the recipe has finished\n')
        # Give beaker-watchdog a chance to notice
        time.sleep(get_conf().get('SLEEP_TIME') * 2)

        self.assert_(not os.path.exists(self.cached_console_log))
        with session.begin():
            self.assertEquals(LogRecipe.query.filter_by(parent=self.recipe,
                    filename=u'console.log').one().server,
                    u'http://elsewhere')
