import numpy as np
from django.test import SimpleTestCase

from analysis.services.nde_data import Axis
from analysis.services.sizing import SizingError, profile, size, size_length


class SizeTests(SimpleTestCase):
    def test_six_db_ends_interpolate_where_the_profile_halves(self):
        v = [0, 0, 10, 40, 80, 100, 80, 40, 10, 0]
        r = size(v, cursor=3)                        # climbs from 40 to the 100 peak
        self.assertEqual((r['peak'], r['peak_amplitude']), (5, 100.0))
        self.assertAlmostEqual(r['level'], 100 * 10 ** (-6 / 20))   # 50.1
        self.assertAlmostEqual(r['start'], 3 + (80 - r['level']) / (80 - 40) * 0 + (r['level'] - 40) / 40)  # 3.25
        self.assertAlmostEqual(r['end'], 6 + (80 - r['level']) / 40)
        self.assertAlmostEqual(r['end'] - r['start'], 2 * (1 + (80 - r['level']) / 40))

    def test_a_higher_point_inside_the_span_becomes_the_peak(self):
        v = [0, 60, 70, 64, 90, 100, 30, 0]
        r = size(v, cursor=2)                        # a local top at 70; 100 is in its -6 dB span
        self.assertEqual(r['peak'], 5)

    def test_threshold_and_errors(self):
        v = [0, 10, 30, 50, 30, 10, 0]
        r = size(v, cursor=3, threshold=20)
        self.assertAlmostEqual(r['start'], 1.5)
        self.assertAlmostEqual(r['end'], 4.5)
        with self.assertRaises(SizingError):
            size([0, 0, 0], cursor=1)
        with self.assertRaises(SizingError):
            size(v, cursor=3, threshold=60)

    def test_profiles_and_metres(self):
        a = np.full((6, 3), np.nan)
        a[1:5, 1] = [20, 100, 100, 20]
        a[2, 2] = 120
        self.assertEqual(list(profile(a, 'scan', 1, 0)), [0, 20, 100, 100, 20, 0])
        self.assertEqual(profile(a, 'scan', 1, 0, 'all')[2], 120)
        group = type('G', (), {'layout': 'beams', 'axes': [Axis('UCoordinate', 6, offset=0.01, resolution=0.001),
                                                          Axis('Beam', 3), Axis('Ultrasound', 10)]})()
        r = size_length({'A_amplitude': a}, group, 'A', scan=2, line=1)
        self.assertAlmostEqual(r['start'], 0.01 + 0.001 * (1 + (100 - r['level']) / 80 * 0 + (r['level'] - 20) / 80))
        self.assertAlmostEqual(r['length'], r['end'] - r['start'])
        with self.assertRaises(SizingError):
            size_length({'A_amplitude': a}, group, 'A', scan=2, line=1, axis='index')
        with self.assertRaises(SizingError):
            size_length({'A_amplitude': a}, group, 'B', scan=2, line=1)
