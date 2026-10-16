"""
L4 on a synthetic weld file in the real page: as drawn it passes; an S-scan drawn 10 % bright, or its
beams drawn 1 mm out of place, fails. (Needs Edge or Chrome; skipped without.)
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np
from django.test import TransactionTestCase

from analysis.tests import builders
from validation import runner
from validation.browser import find_browser
from validation.checks import views
from validation.kit import Kit


@unittest.skipUnless(find_browser(), 'No Edge or Chrome on this PC')
class ViewsTests(TransactionTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        source = os.path.join(self.folder, 'source')
        os.makedirs(source)
        # A fan of 7 beams; a smooth echo of every height across the frame
        rng = np.random.default_rng(3)
        scans, beams, samples = 4, 7, 400
        i = np.arange(samples)
        echo = np.clip(np.sin(i / samples * np.pi) * 34000 * (0.4 + 0.6 * rng.random((scans, beams, 1))), 0, 32767)
        amplitudes = echo.astype(np.int16)
        self.kit = Kit(os.path.join(self.folder, 'kit'))
        self.kit.add(builders.weld_file(source, scans=scans, beams=(40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0), samples=samples,
                                        amplitudes=amplitudes, status=False, period=2e-8), ['decoding'], 'synthetic')

    def l4(self):
        run = runner.execute(runner.create(['L4'], self.kit.root))
        layer = run.results['layers'][0]
        return run, layer, {i['what'] for c in layer['checks'] for i in c['items'] if i['ok'] is False}

    def test_the_page_as_drawn_passes(self):
        run, layer, bad = self.l4()
        self.assertEqual(run.status, 'passed', [i['measured'] for c in layer['checks'] for i in c['items'] if i['ok'] is False] or layer)
        kinds = {c['title'] for c in layer['checks']}
        self.assertTrue({'S-scan', 'A-scan', 'Cursor'} <= kinds, kinds)
        colours = [i for c in layer['checks'] if c['title'] == 'S-scan' for i in c['items'] if i['what'].startswith('Line')]
        self.assertGreaterEqual(len(colours), 6)

    def test_a_bright_s_scan_fails(self):
        bright = views.JS_SSCAN.replace("const H = s.canvas.height", "s.gain = (s.gain || 1) * 1.1; const H = s.canvas.height")
        with mock.patch.object(views, 'JS_SSCAN', bright):
            run, _, bad = self.l4()
        self.assertEqual(run.status, 'failed')
        self.assertTrue(any(w.startswith('Line') for w in bad), bad)

    def test_beams_out_of_place_fail(self):
        shifted = views.JS_SSCAN.replace("const H = s.canvas.height", "s.rays.forEach(r => { r.v0 += 0.001; }); const H = s.canvas.height")
        with mock.patch.object(views, 'JS_SSCAN', shifted):
            run, _, bad = self.l4()
        self.assertEqual(run.status, 'failed')
        self.assertTrue(any(w.startswith('Positions') for w in bad), bad)
