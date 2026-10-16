"""L5 runs the page's real criteria.js in a headless browser: it passes as written, and fails a planted wrong rule."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

from validation.browser import find_browser
from validation.checks import grading


class Context:
    def __init__(self):
        self.out, self.options = [], {}

    def emit(self, c):
        self.out.append(c)

    def progress(self, *a):
        pass

    def message(self, text):
        self.text = text

    def cancelled(self):
        return False


@unittest.skipUnless(find_browser(), 'No Edge or Chrome on this PC')
class GradingTests(SimpleTestCase):
    def run_layer(self):
        context = Context()
        grading.run(context)
        return context.out

    def test_the_case_table_passes(self):
        checks = self.run_layer()
        self.assertGreaterEqual(len(checks), 28)
        self.assertEqual([c['subject'] for c in checks if not c['passed']], [])

    def test_a_wrong_allowed_length_fails(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        with open(finders.find('analysis/js/criteria.js'), encoding='utf-8') as f:
            code = f.read()
        wrong = os.path.join(folder, 'criteria.js')
        with open(wrong, 'w', encoding='utf-8') as f:
            f.write(code.replace('? T / 3 :', '? T / 4 :'))   # T/4 instead of the procedure's T/3
        with mock.patch.object(finders, 'find', lambda path: wrong):
            failed = [c['subject'] for c in self.run_layer() if not c['passed']]
        self.assertIn('B31.3 (§9) · T 1.500 in · 100 % of 80 % · length 0.500 in', failed)
