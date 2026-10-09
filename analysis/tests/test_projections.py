import os
import shutil
import tempfile
import unittest
import unittest.mock

import numpy as np
from django.test import SimpleTestCase, override_settings

from analysis.services import projections
from analysis.services.nde_data import Gate, open_file, read_ascan, read_frame
from analysis.services.readings import evaluate_gates
from analysis.tests import builders

REPORTS = os.path.expanduser('~/Desktop/Reports')


class ProjectionTests(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        override = override_settings(ANALYSIS_CACHE_DIR=os.path.join(self.folder, 'cache'))
        override.enable()
        self.addCleanup(override.disable)

    def assert_same_as_readings(self, path, group, scan, gates, gain=0.0):
        """gates_block over a whole frame == readings.evaluate_gates line by line."""
        raw, _ = read_frame(path, group, scan)
        times = projections.line_times(group, raw.shape[1])
        block = projections.gates_block(group, raw, gates, times, gain)
        for line in range(raw.shape[0]):
            one = raw[line]
            if gain:
                one = np.clip(np.round(one.astype(np.float64) * 10 ** (gain / 20)), -32768, 32767).astype(np.int16)
            single = evaluate_gates(group, group.beams[line], one, gates)
            for letter, result in single.items():
                for name in ('amplitude', 'peak_time', 'crossing_time'):
                    expected = getattr(result, name)
                    got = block[letter][name][line]
                    if expected is None:
                        self.assertTrue(np.isnan(got), (letter, name, line))
                    else:
                        self.assertAlmostEqual(float(got), expected, places=9, msg=(letter, name, line))

    def test_block_gates_match_the_checked_readings(self):
        path = builders.raster_file(self.folder, samples=120)
        group = open_file(path).group(0)
        gates = [Gate(0, 'Gate A', start=0.0, length=1e-6, threshold=5.0),
                 Gate(1, 'Gate B', start=1e-7, length=1e-6, threshold=5.0, sync_mode='GateRelative', sync_gate=0)]
        self.assert_same_as_readings(path, group, 2, gates)
        self.assert_same_as_readings(path, group, 2, gates, gain=6.0)

    def test_build_makes_the_volume_and_cscan(self):
        path = builders.weld_file(self.folder, scans=5, samples=1100)   # > MAX_BINS: max-pooled by 3
        group = open_file(path).group(0)
        status = projections.ensure(path, group, group.gates, background=False)
        self.assertEqual(status['state'], 'done')
        b_scan, info = projections.read_volume_line(path, group, 1)
        self.assertEqual((info['factor'], info['bins'], b_scan.shape), (3, 367, (5, 367)))
        # The builder's samples rise along the A-scan: each bin holds its last sample's value
        raw = read_ascan(path, group, 4, 1)
        expected = min(255, round(raw[5] * group.unit_max / group.raw_max * 255 / projections.VOLUME_FULL))
        self.assertEqual(int(b_scan[4, 1]), expected)
        cscan = projections.read_cscan(path, group, group.gates)
        self.assertEqual(cscan['A_amplitude'].shape, (5, 3))
        single = evaluate_gates(group, group.beams[2], read_ascan(path, group, 3, 2))
        self.assertAlmostEqual(float(cscan['A_amplitude'][3, 2]), single['A'].amplitude, places=4)
        # No data at (0, 0) in the builder's status: nothing in the C-scan there
        self.assertTrue(np.isnan(cscan['A_amplitude'][0, 0]))
        self.assertEqual(projections.ensure(path, group, group.gates)['state'], 'done')

    def test_prune_keeps_the_most_recent(self):
        root = projections.cache_root()
        for i in range(4):
            os.makedirs(os.path.join(root, f'f{i}'))
            os.utime(os.path.join(root, f'f{i}'), (i, i))
        projections.prune(keep=2)
        self.assertEqual(sorted(os.listdir(root)), ['f2', 'f3'])

    @unittest.skipUnless(os.path.isfile(os.path.join(REPORTS, 'sample data', '31e33a wh 12x12.nde')), 'sample not on this PC')
    def test_real_hydroform_frame_matches_line_by_line(self):
        path = os.path.join(REPORTS, 'sample data', '31e33a wh 12x12.nde')
        group = open_file(path).group(0)
        self.assert_same_as_readings(path, group, 118, group.gates)


class NoSynchroTests(SimpleTestCase):
    def test_interface_synced_a_scans_without_sync_have_no_readings(self):
        from analysis.services.nde_data import usable
        group = type('G', (), {'synced_to_interface': True})()
        self.assertEqual(list(usable(group, np.array([1, 5, 0, 3]))), [True, False, False, True])
        group.synced_to_interface = False
        self.assertEqual(list(usable(group, np.array([1, 5, 0]))), [True, True, False])


@unittest.skipUnless(os.path.isfile(os.path.join(REPORTS, 'sample data', '31e33a wh 12x12.nde')), 'sample not on this PC')
class HydroformThicknessMapTests(SimpleTestCase):
    """The C-scan's thickness maps at the cell the user checked in OmniPC (A/-I/ 0.402, T(B/-A/) 0.385 in)."""

    def test_a_minus_i_and_b_minus_a_at_the_omnipc_cell(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(REPORTS, 'sample data', '31e33a wh 12x12.nde')
        with override_settings(ANALYSIS_CACHE_DIR=folder):
            from django.test import Client
            from django.urls import reverse
            group = open_file(path).group(0)
            projections.build(path, group, group.gates)
            with unittest.mock.patch('analysis.views.checked_path', lambda p: p):
                client = Client()
                for gate, frm, expected in (('A', 'I', 0.402), ('B', 'A', 0.385)):
                    response = client.get(reverse('analysis-cscan'), {'path': path, 'gate': gate, 'kind': 'thickness', 'from': frm})
                    values = np.frombuffer(response.content, dtype='<f4').reshape(306, 306)
                    self.assertAlmostEqual(values[118, 29] / 0.0254, expected, delta=0.0006, msg=f'{gate}-{frm}')



class BuildJobTests(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        override = override_settings(ANALYSIS_CACHE_DIR=os.path.join(self.folder, 'cache'))
        override.enable()
        self.addCleanup(override.disable)

    def test_a_cancelled_build_leaves_nothing_and_old_cscans_are_pruned(self):
        path = builders.weld_file(self.folder, scans=6)
        group = open_file(path).group(0)
        with self.assertRaises(projections.Cancelled):
            projections.build(path, group, group.gates, cancelled=lambda: True)
        folder = projections.cache_dir(path)
        self.assertEqual([f for f in os.listdir(folder) if f.endswith('.npz') or f.endswith('.npy')], [])
        for gain in range(projections.KEEP_CSCANS + 2):
            projections.build(path, group, group.gates, gain=float(gain))
        cscans = [f for f in os.listdir(folder) if '_cscan_' in f]
        self.assertEqual(len(cscans), projections.KEEP_CSCANS)
        self.assertIsNotNone(projections.read_cscan(path, group, group.gates, gain=float(projections.KEEP_CSCANS + 1)))
        # Read again: served from memory, the same arrays
        a = projections.read_cscan(path, group, group.gates, gain=float(projections.KEEP_CSCANS + 1))
        b = projections.read_cscan(path, group, group.gates, gain=float(projections.KEEP_CSCANS + 1))
        self.assertIs(a, b)
