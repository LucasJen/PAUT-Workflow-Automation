"""L6: lock the results, a re-run matches them, and a planted change in the app shows."""
import os
import shutil
import tempfile
from unittest import mock

import numpy as np
from django.test import TestCase

from analysis.services import projections
from analysis.tests import builders
from validation import runner
from validation.kit import Kit
from validation.models import ValidationRun


class BaselineTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        source = os.path.join(self.folder, 'source')
        os.makedirs(source)
        amplitudes = np.zeros((6, 3, 50), dtype=np.int16)
        amplitudes[2:4, 1, 30] = 20000            # an indication two scan lines long on beam 1
        self.kit = Kit(os.path.join(self.folder, 'kit'))
        self.kit.add(builders.weld_file(source, scans=6, amplitudes=amplitudes), ['decoding'], 'synthetic')
        self.kit.add(builders.raster_file(source), ['decoding'], 'synthetic')

    def l6(self, **options):
        run = runner.execute(runner.create(['L6'], self.kit.root, options))
        return run, run.results['layers'][0]

    def test_no_baseline_yet_is_said_not_failed(self):
        run, layer = self.l6()
        self.assertEqual(run.status, ValidationRun.PASSED)
        self.assertIn('No approved baseline', layer['message'])

    def test_locked_results_match_and_a_changed_c_scan_fails(self):
        run, layer = self.l6(approve='Test lock')
        self.assertEqual(run.status, ValidationRun.PASSED, layer)
        self.assertTrue(os.path.isfile(os.path.join(self.kit.root, 'baseline', 'baseline.json')))
        run, layer = self.l6()
        self.assertEqual(run.status, ValidationRun.PASSED, [c for c in layer['checks'] if not c['passed']])
        self.assertEqual(len(layer['checks']), 2)
        found = next(i for c in layer['checks'] if 'weld' in c['subject'] for i in c['items'] if i['what'].startswith('Indications'))
        self.assertEqual(found['measured'], '1 indications')
        # The app's gate maps read 1 % high: the C-scans and the sizing must show it
        real = projections.gates_block

        def high(*args, **kwargs):
            out = real(*args, **kwargs)
            for gate in out.values():
                if 'amplitude' in gate:
                    gate['amplitude'] = gate['amplitude'] * 1.01
            return out
        with mock.patch.object(projections, 'gates_block', high):
            run, layer = self.l6()
        self.assertEqual(run.status, ValidationRun.FAILED)
        bad = {i['what'] for c in layer['checks'] for i in c['items'] if i['ok'] is False}
        self.assertIn('C-scan A_amplitude', bad)

    def test_a_changed_reading_fails(self):
        self.l6(approve='Test lock')
        from analysis import views
        real = views.omnipc_reading
        with mock.patch.object(views, 'omnipc_reading', lambda *a, **k: (lambda v: v * 1.001 if isinstance(v, float) else v)(real(*a, **k))):
            run, layer = self.l6()
        self.assertEqual(run.status, ValidationRun.FAILED)
        bad = {i['what'] for c in layer['checks'] for i in c['items'] if i['ok'] is False}
        self.assertIn('Readings on the A-scan grid', bad)

    def test_a_tampered_baseline_is_refused(self):
        self.l6(approve='Test lock')
        with open(os.path.join(self.kit.root, 'baseline', 'baseline.json'), 'a', encoding='utf-8') as f:
            f.write(' ')
        run, _ = self.l6()
        self.assertEqual(run.status, ValidationRun.FAILED)
        self.assertIn('baseline/baseline.json', [f['path'] for f in run.results['kit']['files'] if not f['ok']])
