#!/usr/bin/python
import bkr.server.test.selenium
from bkr.server.test import data_setup
import unittest, time, re, os
from turbogears.database import session

class AddTask(bkr.server.test.selenium.SeleniumTestCase):
    def setUp(self):
        self.verificationErrors = []
        self.selenium = self.get_selenium()
        self.selenium.start()
        sel = self.selenium
        self.test_package = 'tmp-distribution-beaker-task_tests-1.1-0.noarch.rpm'
        self.test_package_name = '/distribution/beaker/task_test'
        self.project_path = os.getcwd() 
        self.package_path = 'bkr/server/test/selenium'
        self.fqpn_task = os.path.join(self.project_path,self.package_path,self.test_package)
        try:
            self.login()
        except AssertionError, e:
            self.verificationErrors.append('Could not login:%s' % e)

    def test_two(self):
        sel = self.selenium
        sel.open("/")
        sel.click("link=New Task")
        sel.wait_for_page_to_load("3000")
        try:
            sel.type("task_task_rpm", "%s" % self.fqpn_task)
            sel.click("//input[@value='Submit Data']")
        except AssertionError,e:
            self.verificationErrors.append('Could not submit data')

        sel.wait_for_page_to_load("3000")
        sel.type("simplesearch", "task_tests")
        sel.click("search")
        sel.wait_for_page_to_load("3000")
        try: 
            self.failUnless(sel.is_text_present(self.test_package_name))
        except AssertionError, e:
            self.verificationErrors.append('Could not verify package was added')
    
    def tearDown(self):
        self.selenium.stop()
        self.assertEqual([], self.verificationErrors)

if __name__ == "__main__":
    unittest.main()
