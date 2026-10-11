"""Finding indications on the gate map and sizing each one (80 % FSH, dB-drop length, height, PA^)."""
import math
import os
import shutil
import tempfile

import numpy as np
from django.test import SimpleTestCase, override_settings

from analysis.services import projections
from analysis.services.detection import find_regions, label, merge
from analysis.services.geometry import fold_depth, position
from analysis.services.nde_data import open_file
from analysis.services.readings import evaluate_gates, omnipc_reading
from analysis.services.sizing import SizingError, gain_to_target, size_indication
from analysis.tests import builders

RAW = 32767 / 200.0   # raw per % (unitMax 200 %)


class FindRegionTests(SimpleTestCase):
    def test_label_joins_diagonals_and_keeps_others_apart(self):
        mask = np.array([[1, 0, 0, 0],
                         [0, 1, 0, 1],
                         [0, 0, 0, 1],
                         [1, 1, 0, 0]], dtype=bool)
        labels, n = label(mask)
        self.assertEqual(n, 3)
        self.assertEqual(labels[0, 0], labels[1, 1])
        self.assertNotEqual(labels[1, 3], labels[3, 0])

    def test_two_flaws_their_peaks_and_spans(self):
        a = np.full((20, 5), np.nan)
        a[2:6, 1:3] = 30
        a[4, 2] = 90
        a[12:15, 3] = [25, 60, 25]
        regions = find_regions(a, 20)
        self.assertEqual(len(regions), 2)
        first, second = regions
        self.assertEqual((first['scan_lo'], first['scan_hi'], first['line_lo'], first['line_hi']), (2, 5, 1, 2))
        self.assertEqual((first['peak_scan'], first['peak_line'], first['peak_amplitude']), (4, 2, 90.0))
        self.assertEqual((second['peak_scan'], second['peak_line']), (13, 3))

    def test_a_short_dip_under_the_threshold_merges(self):
        a = np.zeros((20, 3))
        a[2:6, 1] = 50
        a[8:11, 1] = 70        # two positions under the threshold between them
        a[8:11, 0] = 0
        self.assertEqual(len(find_regions(a, 20, merge_gap=2)), 1)
        self.assertEqual(len(find_regions(a, 20, merge_gap=1)), 2)
        merged = find_regions(a, 20, merge_gap=2)[0]
        self.assertEqual((merged['scan_lo'], merged['scan_hi'], merged['peak_scan']), (2, 10, 8))
        # Lines that don't meet stay apart, however close
        self.assertEqual(len(merge([{'scan_lo': 0, 'scan_hi': 2, 'line_lo': 0, 'line_hi': 0, 'peak_scan': 1,
                                     'peak_line': 0, 'peak_amplitude': 50, 'cells': 3},
                                    {'scan_lo': 3, 'scan_hi': 5, 'line_lo': 4, 'line_hi': 4, 'peak_scan': 4,
                                     'peak_line': 4, 'peak_amplitude': 50, 'cells': 3}], 2)), 2)

    def test_minimums_and_threshold(self):
        a = np.zeros((10, 4))
        a[1, 0] = 50                  # one position (lines apart from the other, so never merged)
        a[4:8, 2] = 50                # four positions on one line
        self.assertEqual(len(find_regions(a, 20)), 2)
        self.assertEqual(len(find_regions(a, 20, min_scans=2)), 1)
        self.assertEqual(len(find_regions(a, 20, min_lines=2)), 0)
        self.assertEqual(len(find_regions(a, 60)), 0)
        a[4, 2] = 20                  # exactly the threshold breaks it
        self.assertEqual(find_regions(a, 20, min_scans=2)[0]['scan_lo'], 4)


class GainTests(SimpleTestCase):
    def test_gain_to_eighty_percent(self):
        self.assertAlmostEqual(gain_to_target(40), 20 * math.log10(2))        # +6.02 dB
        self.assertAlmostEqual(gain_to_target(160), -20 * math.log10(2))
        self.assertEqual(gain_to_target(80), 0.0)
        self.assertEqual(gain_to_target(0), 0.0)


def weld_with_flaw(folder, saturate=False):
    """
    A 20-position sectorial scan (45 / 55 / 65 deg) with one reflector: on the 55 deg beam at samples
    60-64 (40 / 80 / 100 / 80 / 40 % at the peak), half that on the other beams, rising and falling
    along the scan from position 4 to 12 (peak at 8).
    """
    scans, samples = 20, 200
    along = {4: 10, 5: 30, 6: 60, 7: 90, 8: 100, 9: 90, 10: 60, 11: 30, 12: 10}
    shape = np.array([40, 80, 100, 80, 40], dtype=float)
    data = np.zeros((scans, 3, samples), dtype=np.int16)
    for scan, percent in along.items():
        for beam, share in ((0, 0.5), (1, 1.0), (2, 0.5)):
            data[scan, beam, 60:65] = np.round(shape * share * percent / 100 * RAW)
    if saturate:
        data[8, 1, 62] = 32767
    return builders.weld_file(folder, scans=scans, samples=samples, amplitudes=data)


class SizeIndicationTests(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        override = override_settings(ANALYSIS_CACHE_DIR=os.path.join(self.folder, 'cache'))
        override.enable()
        self.addCleanup(override.disable)

    def sized(self, method='6', saturate=False):
        path = weld_with_flaw(self.folder, saturate)
        info = open_file(path)
        group = info.group(0)
        projections.build(path, group, group.gates)
        cscan = projections.read_cscan(path, group, group.gates)
        regions = find_regions(cscan['A_amplitude'], group.gates[0].threshold)
        self.assertEqual(len(regions), 1)
        return path, info, group, regions[0], size_indication(path, info, group, group.gates, cscan, 'A',
                                                              regions[0], method)

    def test_the_region_found(self):
        _, _, _, region, _ = self.sized()
        # >= 20 %: positions 5-11 on the 55 deg beam (30 % at 5), 6-10 on the others (half)
        self.assertEqual((region['scan_lo'], region['scan_hi'], region['peak_scan'], region['peak_line']), (5, 11, 8, 1))
        self.assertEqual((region['line_lo'], region['line_hi']), (0, 2))

    def test_length_by_six_db_along_the_scan(self):
        _, _, _, _, r = self.sized()
        level = 100 * 10 ** (-6 / 20)                       # 50.1 % of the 100 % peak
        start = 5 + (level - 30) / (60 - 30)                 # between position 5 (30 %) and 6 (60 %)
        end = 10 + (60 - level) / (60 - 30)                  # between 10 (60 %) and 11 (30 %)
        self.assertAlmostEqual(r['scan_start'], start * 0.001, places=5)
        self.assertAlmostEqual(r['scan_end'], end * 0.001, places=5)
        self.assertAlmostEqual(r['length'], (end - start) * 0.001, places=5)
        self.assertEqual((r['peak_scan'], r['peak_line'], r['peak_sample']), (8, 1, 62))
        self.assertAlmostEqual(r['peak_amplitude'], 100.0, places=1)
        self.assertAlmostEqual(r['gain_db'], 20 * math.log10(80 / r['peak_amplitude']))
        self.assertFalse(r['saturated'])

    def test_height_and_axial_by_six_db_on_the_s_scan(self):
        path, info, group, _, r = self.sized()
        beam = group.beams[1]
        # -6 dB: the 55 deg beam's samples 61-63 (80 / 100 / 80 %); the other beams' 50 % are under 50.1 %
        tops = [position(group, beam, i)[2] for i in (61, 62, 63)]
        self.assertAlmostEqual(r['height'], tops[-1] - tops[0], places=9)
        self.assertAlmostEqual(r['height'], 3240 * 1e-7 / 2 * math.cos(math.radians(55)), places=9)   # 0.093 mm
        self.assertAlmostEqual(r['top'], tops[0], places=9)
        self.assertAlmostEqual(r['depth'], r['top'])
        # The axial position is the peak's PA^, as the readings give it
        raw, _ = __import__('analysis.services.nde_data', fromlist=['read_frame']).read_frame(path, group, 8)
        results = evaluate_gates(group, beam, raw[1], group.gates)
        self.assertAlmostEqual(r['axial'], omnipc_reading('PA^', results, beam, info), places=9)
        self.assertAlmostEqual(r['peak_depth'], omnipc_reading('DA^', results, beam, info), places=9)
        self.assertLessEqual(r['axial_start'], r['axial'])
        self.assertGreaterEqual(r['axial_end'], r['axial'])
        self.assertEqual(r['angle'], 55.0)

    def test_twelve_db_takes_in_the_neighbouring_beams(self):
        _, _, group, _, six = self.sized('6')
        _, _, _, _, twelve = self.sized('12')
        self.assertGreater(twelve['length'], six['length'])
        self.assertGreater(twelve['height'], six['height'])
        # -12 dB (25.1 %): the 45 / 65 deg beams' samples 61-63 (40 / 50 / 40 %) join; the deepest is on 65 deg
        depths = [fold_depth(position(group, group.beams[b], i)[2], 0.0125)[0]
                  for b, samples in ((0, (61, 62, 63)), (1, range(60, 65)), (2, (61, 62, 63))) for i in samples]
        self.assertAlmostEqual(twelve['height'], max(depths) - min(depths), places=9)

    def test_a_saturated_peak_is_flagged(self):
        _, _, _, _, r = self.sized(saturate=True)
        self.assertTrue(r['saturated'])
        self.assertLess(r['gain_db'], 0)

    def test_unknown_method(self):
        path = weld_with_flaw(self.folder)
        info = open_file(path)
        group = info.group(0)
        with self.assertRaises(SizingError):
            size_indication(path, info, group, group.gates, {'A_amplitude': np.zeros((20, 3))}, 'A',
                            {'peak_scan': 8, 'peak_line': 1, 'line_lo': 0, 'line_hi': 2}, method='9')
