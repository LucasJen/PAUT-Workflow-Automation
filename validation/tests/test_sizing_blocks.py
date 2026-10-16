"""
L2 and L3 on a synthetic weld with one indication worked out by hand: beam 1 (55 deg), sample 50
(t = 6.5 us: sound path 10.53 mm, depth 6.040 mm), over scan lines 3-8 rising to full scale and back.
Its -6 dB ends (half the peak) fall at scan 3.6 and 7.4 (1 mm steps): 0.142 and 0.291 in.
"""
import json
import math
import os
import shutil
import tempfile

import numpy as np
from django.test import TestCase

from analysis.tests import builders
from validation import importer, runner
from validation.kit import Kit

IN = 0.0254
PROFILE = [0, 0, 0, 10000, 20000, 32000, 32000, 20000, 10000, 0, 0, 0]
SP = 3240 * (4e-6 + 50 * 5e-8) / 2
DEPTH = SP * math.cos(math.radians(55)) / IN
PA = (-0.0195 + SP * math.sin(math.radians(55))) / IN


def export_csv(rows):
    head = '﻿#,Group,Scan,Index,Angle,VPA,A%,DA^,PA^,S(r),S(m),Reference, Type, Status, Comment\n'
    cell = lambda v, u: f'"=""{v:.3f} {u}"""'
    body = ''.join(f"{n},GR-1,{cell(scan, 'in')},{cell(-0.5, 'in')},{cell(angle, '°')},-,{cell(97.6, '%')},{cell(da, 'in')},{cell(pa, 'in')},"
                   f"{cell(sr, 'in')},{cell(sm, 'in')},,None,NotEvaluated,\n" for n, (scan, angle, da, pa, sr, sm) in enumerate(rows, 1))
    return head + body


class SizingAndBlockTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        source = os.path.join(self.folder, 'source')
        os.makedirs(source)
        amplitudes = np.zeros((12, 3, 100), dtype=np.int16)
        for scan, raw in enumerate(PROFILE):
            amplitudes[scan, 1, 50] = raw
        self.kit = Kit(os.path.join(self.folder, 'kit'))
        self.nde = self.kit.add(builders.weld_file(source, scans=12, samples=100, amplitudes=amplitudes, status=False), ['decoding'], 'synthetic')

    def import_rows(self, rows, **options):
        path = os.path.join(self.folder, 'indications.csv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(export_csv(rows))
        return importer.import_export(self.kit, path, self.nde, 'synthetic export', **options)

    def layer(self, lid):
        run = runner.execute(runner.create([lid], self.kit.root))
        return run, run.results['layers'][0]

    def test_sizing_at_omnipcs_cursors_passes_and_a_moved_end_fails(self):
        self.import_rows([(0.197, 55.0, DEPTH, PA, 0.142, 0.291)], sizing='6')
        run, layer = self.layer('L2')
        self.assertEqual(run.status, 'passed', layer)
        self.assertEqual([c['title'] for c in layer['checks']], ['Sizing'])
        self.import_rows([(0.197, 55.0, DEPTH, PA, 0.142, 0.350)], sizing='6')   # the end a couple of steps out
        run, layer = self.layer('L2')
        self.assertEqual(run.status, 'failed')

    def test_detection_finds_the_logged_indication_and_misses_a_made_up_one(self):
        self.import_rows([(0.197, 55.0, DEPTH, PA, 0.142, 0.291)], complete=True)
        run, layer = self.layer('L2')
        self.assertEqual(run.status, 'passed', layer)
        self.assertIn('1 of 1 logged indications found', layer['checks'][0]['subject'])
        self.import_rows([(0.197, 55.0, DEPTH, PA, 0.142, 0.291), (0.394, 45.0, 0.1, 0.1, 0.38, 0.41)], complete=True)
        run, layer = self.layer('L2')
        self.assertEqual(run.status, 'failed')

    def write_block(self, depth):
        points = next(e for e in self.kit.files if e['path'].startswith('points/'))
        block = {'block': 'Test block', 'units': 'in', 'points': points['path'],
                 'reflectors': [{'indication': 1, 'name': 'SDH', 'depth': depth, 'tolerance': {'depth': 0.02}}]}
        path = os.path.join(self.folder, 'block.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(block, f)
        self.kit.add(path, ['block'], 'synthetic block')

    def test_a_reflector_where_the_block_has_it_passes_and_one_drawn_elsewhere_fails(self):
        self.import_rows([(0.197, 55.0, DEPTH + 0.002, PA, 0.142, 0.291)])   # OmniPC 0.002 in deep
        self.write_block(round(DEPTH, 3))
        run, layer = self.layer('L3')
        self.assertEqual(run.status, 'passed', layer)
        items = {i['what']: i for i in layer['checks'][0]['items']}
        self.assertIn('Depth: the app as close as OmniPC', items)
        self.write_block(round(DEPTH, 3) + 0.05)
        run, layer = self.layer('L3')
        self.assertEqual(run.status, 'failed')
