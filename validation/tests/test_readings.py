"""
L1 on a synthetic weld file whose readings are worked out by hand here (not with the app's code), sent
through the importer as an OmniPC export would be; then planted errors - in the export, and in the
app - must fail.
"""
import math
import os
import shutil
import tempfile
from unittest import mock

import numpy as np
from django.test import TestCase

from analysis.tests import builders
from validation import importer, runner
from validation.models import ValidationRun
from validation.kit import Kit

IN = 0.0254
# The builder's weld file: 3240 m/s, beam 1 at 55 deg with its exit point at -19.5 mm, first sample at
# 4 us, 50 ns a sample, 200 % at raw 32767, a 12.5 mm plate. One echo at scan 2, beam 1, sample 30.
RAW, SAMPLE, ANGLE, V_OFFSET = 20000, 30, 55.0, -0.0195
T = 4e-6 + SAMPLE * 5e-8
SP = 3240 * T / 2
EXPECTED = {
    'A%': RAW * 200 / 32767,
    'SA^': SP / IN,
    'DA^': SP * math.cos(math.radians(ANGLE)) / IN,
    'ViA^': (V_OFFSET + SP * math.sin(math.radians(ANGLE))) / IN,
}
EXPECTED['PA^'] = EXPECTED['ViA^']   # no wedge position in the file: from 0


def omnipc_csv(values, scan='0.079', angle='55.000'):
    q = lambda v, unit: f'"=""{v:.3f} {unit}"""'
    cells = ','.join(q(values[k], '%' if '%' in k else 'in') for k in ('A%', 'DA^', 'PA^', 'SA^', 'ViA^'))
    return ('﻿#,Group,Scan,Index,Angle,VPA,A%,DA^,PA^,SA^,ViA^,S(m-r),Reference, Type, Status, Comment\n'
            f'1,GR-1,"=""{scan} in""","=""-0.500 in""","=""{angle} °""",-,{cells},"=""2.472 in""",,None,NotEvaluated,\n')


SETUP_CSV = ('﻿Setup\nDelta Vt,0.0 dB,Gates,Start,Width,Threshold,Synchro,Peak Selection,Polarity,\n'
             'A,0.400 in,1.800 in,20 %,Pulse,Highest,Positive,\n\n')


class ReadingsLayerTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        amplitudes = np.zeros((4, 3, 50), dtype=np.int16)
        amplitudes[2, 1, SAMPLE] = RAW
        source = os.path.join(self.folder, 'source')
        os.makedirs(source)
        self.kit = Kit(os.path.join(self.folder, 'kit'))
        self.nde = self.kit.add(builders.weld_file(source, amplitudes=amplitudes), ['decoding'], 'synthetic')

    def export(self, values, **where):
        path = os.path.join(self.folder, 'indications.csv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(omnipc_csv(values, **where))
        with open(os.path.join(self.folder, 'setup.csv'), 'w', encoding='utf-8') as f:
            f.write(SETUP_CSV)
        return importer.import_export(self.kit, path, self.nde, 'synthetic OmniPC export')

    def run_l1(self):
        run = runner.execute(runner.create(['L1'], self.kit.root))
        return run, run.results['layers'][0]['checks']

    def test_the_export_is_placed_on_the_right_cell(self):
        rows = importer.parse_indications(omnipc_csv(EXPECTED))
        self.assertEqual(rows[0]['scan'], ('0.079', 'in'))
        self.assertEqual(importer.parse_setup(SETUP_CSV), {'A': 'maxpeak'})
        spec = importer.to_points(rows, self.kit.full_path(self.nde), self.nde['path'])[0]
        point = spec['points'][0]
        self.assertEqual((point['scan'], point['beam'], point['angle']), (2, 1, 55.0))
        self.assertEqual(point['decimals']['SA^'], 3)
        self.assertIn('S(m-r)', point['not_compared'])

    def test_hand_worked_readings_pass_to_the_digit(self):
        self.export(EXPECTED)
        run, checks = self.run_l1()
        self.assertEqual(run.status, ValidationRun.PASSED, checks)
        items = {i['what']: i for i in checks[0]['items']}
        self.assertEqual(set(items), {'A%', 'DA^', 'PA^', 'SA^', 'ViA^', 'S(m-r)'})
        self.assertIsNone(items['S(m-r)']['ok'])   # shown, not compared: no cursor positions in the export

    def test_a_reading_off_by_a_displayed_digit_fails(self):
        self.export({**EXPECTED, 'SA^': EXPECTED['SA^'] + 0.002})
        run, checks = self.run_l1()
        self.assertEqual(run.status, ValidationRun.FAILED)
        bad = [i['what'] for i in checks[0]['items'] if i['ok'] is False]
        self.assertEqual(bad, ['SA^'])

    def test_the_app_reading_one_sample_late_fails(self):
        self.export(EXPECTED)
        from analysis import views
        real = views.evaluate_gates

        def late(group, beam, raw, gates=None, interface=None):
            results = real(group, beam, raw, gates, interface)
            for r in results.values():
                if r.position_time is not None:
                    r.position_time += 5e-8
            return results
        with mock.patch.object(views, 'evaluate_gates', late):
            run, checks = self.run_l1()
        self.assertEqual(run.status, ValidationRun.FAILED)
        bad = {i['what'] for i in checks[0]['items'] if i['ok'] is False}
        self.assertTrue({'SA^', 'DA^'} <= bad, bad)

    def test_an_angle_not_in_the_file_is_reported_not_skipped(self):
        self.export(EXPECTED, angle='57.000')
        run, checks = self.run_l1()
        self.assertEqual(run.status, ValidationRun.FAILED)
        self.assertIn('No beam at 57.000', checks[0]['items'][0]['measured'])
