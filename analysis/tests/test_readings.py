import glob
import json
import os
import shutil
import tempfile
import unittest

import numpy as np
from django.test import SimpleTestCase

from analysis.services.nde_data import Gate, open_file, read_ascan
from analysis.services.readings import evaluate_gates, gate_letter, omnipc_reading
from analysis.tests import builders

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures', 'omnipc_readings')
REPORTS = os.path.expanduser('~/Desktop/Reports')
IN = 0.0254


class GateTests(SimpleTestCase):
    """Synthetic A-scans on the raster builder's group (5890 m/s, 0 deg, 20 ns samples from -1 us)."""

    def setUp(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.group = open_file(builders.raster_file(folder, samples=400)).group(0)
        self.beam = self.group.beams[0]
        self.raw_per_percent = self.group.raw_max / self.group.unit_max

    def ascan(self, echoes):
        """Raw samples with {sample index: percent} echoes on a flat 2 % floor."""
        a = np.full(400, 2.0)
        for i, percent in echoes.items():
            a[i] = percent
        return np.round(a * self.raw_per_percent).astype(np.int16)

    def test_crossing_is_the_first_whole_sample_at_or_above_threshold(self):
        gates = [Gate(0, 'Gate A', start=0.0, length=6e-6, threshold=20.0)]
        # sample 100 = -1 us + 100 * 20 ns = 1 us; sample 101 reaches exactly 20 %
        results = evaluate_gates(self.group, self.beam, self.ascan({100: 19.0, 101: 20.0, 120: 90.0}), gates)
        a = results['A']
        self.assertAlmostEqual(a.crossing_time, -1e-6 + 101 * 2e-8)
        self.assertAlmostEqual(a.amplitude, 90.0, places=1)
        self.assertAlmostEqual(a.peak_time, -1e-6 + 120 * 2e-8)

    def test_amplitude_counts_even_without_a_crossing(self):
        gates = [Gate(0, 'Gate A', start=0.0, length=6e-6, threshold=50.0)]
        a = evaluate_gates(self.group, self.beam, self.ascan({150: 30.0}), gates)['A']
        self.assertFalse(a.crossed)
        self.assertAlmostEqual(a.amplitude, 30.0, places=1)

    def test_relative_gates_start_from_their_sync_gates_crossing(self):
        gates = [Gate(1, 'Gate B', start=1e-6, length=5e-6, threshold=20.0, sync_mode='GateRelative', sync_gate=0,
                      trigger='Crossing'),
                 Gate(0, 'Gate A', start=0.0, length=3e-6, threshold=20.0)]
        # A crosses at sample 100 (1 us); B opens 1 us later, so the echo at sample 140 (1.8 us) is
        # before it and the one at sample 200 (3 us) is found
        results = evaluate_gates(self.group, self.beam, self.ascan({100: 60.0, 140: 70.0, 200: 40.0}), gates)
        self.assertAlmostEqual(results['B'].start, 2e-6)
        self.assertAlmostEqual(results['B'].crossing_time, 3e-6)
        thickness = omnipc_reading('T(B/-A/)', results, self.beam)
        self.assertAlmostEqual(thickness, builders.LONGITUDINAL * 2e-6 / 2)
        # No crossing in the sync gate: the relative gate isn't placed
        results = evaluate_gates(self.group, self.beam, self.ascan({}), gates)
        self.assertFalse(results['B'].found)
        self.assertIsNone(omnipc_reading('B%1', results, self.beam))

    def test_an_a_scan_retimed_to_the_interface_starts_at_gate_is_crossing(self):
        self.group.synchro_mode = 'SynchroGateRelative'
        gates = [Gate(0, 'Gate I', start=1.5e-5, length=1e-5, threshold=35.0),
                 Gate(1, 'Gate A', start=1e-6, length=6e-6, threshold=20.0, sync_mode='GateRelative', sync_gate=0)]
        results = evaluate_gates(self.group, self.beam, self.ascan({250: 80.0}), gates)   # 4 us after the interface
        self.assertEqual(results['I'].crossing_time, 0.0)
        self.assertAlmostEqual(omnipc_reading('A/-I/', results, self.beam), builders.LONGITUDINAL * 4e-6 / 2)
        with self.assertRaises(KeyError):
            omnipc_reading('ViA^', results, self.beam)

    def test_gate_letters(self):
        self.assertEqual([gate_letter(n) for n in ('Gate A', 'Gate I', 'B', '')], ['A', 'I', 'B', ''])


class OmniPCReadingsTests(SimpleTestCase):
    """Every point in fixtures/omnipc_readings, recomputed from the file's raw A-scans (skipped when
    the .nde file isn't on this PC)."""

    def test_readings_match_omnipc(self):
        fixtures = sorted(glob.glob(os.path.join(FIXTURES, '*.json')))
        self.assertTrue(fixtures)
        checked = 0
        for fixture in fixtures:
            with open(fixture, encoding='utf-8') as f:
                spec = json.load(f)
            path = spec['file'] if os.path.isabs(spec['file']) else os.path.join(REPORTS, spec['file'])
            if not os.path.isfile(path):
                continue
            group = open_file(path).group(spec.get('group', 0))
            to_unit = IN if spec.get('units', 'in') == 'in' else 0.001
            for point in spec['points']:
                lateral = point.get('index', point.get('beam'))
                beam = group.beams[lateral]
                results = evaluate_gates(group, beam, read_ascan(path, group, point['scan'], lateral))
                for name, expected in point['expected'].items():
                    value = omnipc_reading(name, results, beam)
                    if '%' not in name:
                        value /= to_unit
                    with self.subTest(fixture=os.path.basename(fixture), reading=name):
                        self.assertAlmostEqual(value, expected, delta=point['tolerance'][name])
                    checked += 1
        if not checked:
            raise unittest.SkipTest('None of the OmniPC fixture files are on this PC.')
