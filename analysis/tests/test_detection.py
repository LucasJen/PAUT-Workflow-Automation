"""Finding indications on the gate map and sizing each one (80 % FSH, dB-drop length, height, PA^)."""
import json
import math
import os
import shutil
import tempfile
import time

import numpy as np
from urllib.parse import urlencode

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from analysis.services import projections
from analysis.services.detection import find_regions, label, merge
from analysis.services.geometry import fold_depth, position
from analysis.services.nde_data import open_file
from analysis.services.readings import evaluate_gates, omnipc_reading
from analysis.services.sizing import SizingError, gain_to_target, size_in_box, size_indication
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


class FoldedSpanTests(SimpleTestCase):
    def test_spans_as_drawn_fold_into_the_part(self):
        from analysis.services.sizing import folded_span
        T = 0.01
        self.assertEqual(folded_span(0.002, 0.004, T), (0.002, 0.004))
        lo, hi = folded_span(0.013, 0.016, T)             # leg 2: comes back up from the back wall
        self.assertAlmostEqual(lo, 0.004); self.assertAlmostEqual(hi, 0.007)
        lo, hi = folded_span(0.008, 0.012, T)             # across the back wall: down to it
        self.assertAlmostEqual(lo, 0.008); self.assertAlmostEqual(hi, 0.01)
        self.assertEqual(folded_span(0.004, 0.002, None), (0.002, 0.004))


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
        self.assertAlmostEqual(r['view_top'], r['top'])          # leg 1: drawn where it is
        self.assertAlmostEqual(r['thickness'], 0.0125)
        # The axial position is the peak's PA^, as the readings give it
        raw, _ = __import__('analysis.services.nde_data', fromlist=['read_frame']).read_frame(path, group, 8)
        results = evaluate_gates(group, beam, raw[1], [__import__('dataclasses').replace(g, detection='maxpeak') for g in group.gates])
        self.assertAlmostEqual(r['axial'], omnipc_reading('PA^', results, beam, info), places=9)   # the max peak's
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

    def test_contour_sizing_keeps_inside_the_box(self):
        path, info, group, _, whole = self.sized()
        cscan = projections.read_cscan(path, group, group.gates)
        # The box cuts the flaw after position 9: its -6 dB end stops there (9 is 90 %, nothing after)
        r = size_in_box(path, info, group, group.gates, cscan, 'A', (3, 9, 0, 2))
        self.assertEqual((r['peak_scan'], r['peak_line']), (8, 1))
        self.assertAlmostEqual(r['scan_start'], whole['scan_start'], places=9)
        self.assertLess(r['scan_end'], whole['scan_end'])
        self.assertLessEqual(r['scan_end'], 9.5 * 0.001 + 1e-12)
        self.assertTrue(r['contour'])
        self.assertFalse(r['auto'])
        self.assertAlmostEqual(r['height'], whole['height'], places=9)
        # Only the tail in the box: its own peak (60 % at position 10) is sized, not the stronger one outside
        tail = size_in_box(path, info, group, group.gates, cscan, 'A', (10, 14, 0, 2))
        self.assertEqual(tail['peak_scan'], 10)
        self.assertGreaterEqual(tail['scan_start'], 9.5 * 0.001 - 1e-12)
        with self.assertRaises(SizingError):
            size_in_box(path, info, group, group.gates, cscan, 'A', (15, 19, 0, 2))

    def test_unknown_method(self):
        path = weld_with_flaw(self.folder)
        info = open_file(path)
        group = info.group(0)
        with self.assertRaises(SizingError):
            size_indication(path, info, group, group.gates, {'A_amplitude': np.zeros((20, 3))}, 'A',
                            {'peak_scan': 8, 'peak_line': 1, 'line_lo': 0, 'line_hi': 2}, method='9')


class DetectApiTests(TestCase):
    """Find indications (detect.json), the review status, and sizing again (resize.json)."""

    def setUp(self):
        from reports.models import WorkingFolder
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        override = override_settings(ANALYSIS_CACHE_DIR=os.path.join(self.folder, '.cache'))
        override.enable()
        self.addCleanup(override.disable)
        WorkingFolder.objects.all().delete()
        WorkingFolder.objects.create(path=self.folder, report_type='paut_weld')
        self.path = weld_with_flaw(self.folder)
        self.query = urlencode({'path': self.path, 'group': 0})

    def detect(self, **settings):
        return self.client.post(f"{reverse('analysis-detect')}?{self.query}", json.dumps(settings),
                                content_type='application/json')

    def built(self):
        group = open_file(self.path).group(0)
        projections.ensure(self.path, group, group.gates, background=False)

    def test_builds_first_then_finds_and_sizes(self):
        response = self.detect()
        self.assertEqual(response.status_code, 409)           # the C-scan is being built (in the background)
        for _ in range(200):
            if response.status_code != 409:
                break
            time.sleep(0.05)
            response = self.detect(method='6')
        data = response.json()
        self.assertEqual(data['found'], 1)
        item = data['indications'][0]
        self.assertEqual((item['status'], item['source'], item['number']), ('unreviewed', 'auto', 1))
        self.assertEqual((item['scan'], item['lateral']), (8, 1))
        self.assertAlmostEqual(item['sizing']['length'], item['readings']['Length'])
        self.assertIn('Height', item['readings'])
        self.assertAlmostEqual(item['gain'], item['sizing']['gain_db'])

    def test_a_new_run_replaces_unreviewed_finds_only(self):
        self.built()
        self.detect()
        self.assertEqual(len(self.detect().json()['indications']), 1)          # replaced, not doubled
        edit = reverse('analysis-indication', args=[self.detect().json()['indications'][0]['id']])
        self.client.post(edit, json.dumps({'status': 'accepted'}), content_type='application/json')
        again = self.detect().json()
        self.assertEqual((again['found'], again['kept'], again['overlapping']), (0, 1, 1))   # kept, the find on top left out
        self.assertEqual(again['indications'][0]['status'], 'accepted')
        bad = self.client.post(edit, json.dumps({'status': 'maybe'}), content_type='application/json')
        self.assertEqual(bad.status_code, 400)

    def test_settings_threshold_and_minimum_length(self):
        self.built()
        self.assertEqual(self.detect(threshold=150).json()['found'], 0)
        self.assertEqual(self.detect(min_length=0.01).json()['found'], 0)      # 7 positions = 7 mm
        self.assertEqual(self.detect(min_length=0.005).json()['found'], 1)
        self.assertEqual(self.detect(method='9').status_code, 400)

    def test_resize_by_another_drop_and_by_hand(self):
        self.built()
        item = self.detect(method='6').json()['indications'][0]
        url = f"{reverse('analysis-resize', args=[item['id']])}?{self.query}"
        twelve = self.client.post(url, json.dumps({'method': '12'}), content_type='application/json').json()
        self.assertEqual(twelve['sizing']['method'], '12')
        self.assertGreater(twelve['sizing']['length'], item['sizing']['length'])
        self.assertEqual(twelve['sizing']['original']['method'], '6')
        hand = self.client.post(url, json.dumps({'manual': {'scan_start': 0.009, 'scan_end': 0.005, 'top': 0.006, 'bottom': 0.0065}}),
                                content_type='application/json').json()['sizing']
        self.assertTrue(hand['edited'])
        self.assertAlmostEqual(hand['length'], 0.004)                           # ends put in order
        self.assertAlmostEqual(hand['height'], 0.0005)
        self.assertEqual(hand['original']['method'], '6')                       # the first sizing kept
        drawn = self.client.post(url, json.dumps({'manual': {'view_top': 0.0130, 'view_bottom': 0.0136}}),
                                 content_type='application/json').json()['sizing']
        self.assertAlmostEqual(drawn['top'], 0.0125 - 0.0011)                    # leg 2, folded at the 12.5 mm back wall
        self.assertAlmostEqual(drawn['height'], 0.0006)
        self.assertEqual(self.client.post(url, json.dumps({'manual': {'top': 'x'}}),
                                          content_type='application/json').status_code, 400)
