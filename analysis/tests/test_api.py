import json
import os
import shutil
import tempfile

import numpy as np
from django.test import TestCase
from django.urls import reverse

from analysis.tests import builders
from reports.models import WorkingFolder


class ApiTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        WorkingFolder.objects.all().delete()
        WorkingFolder.objects.create(path=self.folder, report_type='paut_weld')
        os.makedirs(os.path.join(self.folder, 'job'))
        self.weld = builders.weld_file(os.path.join(self.folder, 'job'))
        self.raster = builders.raster_file(self.folder)

    def test_lists_nde_files_in_the_working_folders(self):
        data = self.client.get(reverse('analysis-files')).json()
        self.assertEqual(sorted(f['name'] for f in data['files']), ['raster.nde', 'weld.nde'])
        self.assertEqual({f['folder'] for f in data['files']}, {'job', '.'})

    def test_file_info_carries_groups_rays_and_probe(self):
        data = self.client.get(reverse('analysis-file'), {'path': self.weld}).json()
        group = data['groups'][0]
        self.assertEqual((group['layout'], group['shape']), ('beams', [4, 3, 50]))
        self.assertEqual(len(group['rays']), 3)
        self.assertAlmostEqual(group['rays'][0]['dz'], 0.7071, places=4)
        self.assertFalse(group['synced_to_interface'])

    def test_frame_is_raw_int16_then_status(self):
        response = self.client.get(reverse('analysis-frame'), {'path': self.weld, 'group': 0, 'scan': 2})
        self.assertEqual((response['X-Lateral'], response['X-Samples'], response['X-Status']), ('3', '50', '1'))
        body = response.content
        samples = np.frombuffer(body[:3 * 50 * 2], dtype='<i2').reshape(3, 50)
        self.assertEqual((samples[1, 7], samples[2, 49]), (2107, 2249))
        self.assertEqual(list(body[3 * 50 * 2:]), [1, 1, 1])
        raster = self.client.get(reverse('analysis-frame'), {'path': self.raster, 'scan': 0})
        self.assertEqual(raster['X-Status'], '0')
        self.assertEqual(len(raster.content), 4 * 40 * 2)

    def test_readings_with_soft_gain(self):
        args = {'path': self.weld, 'group': 0, 'scan': 3, 'lateral': 2}
        plain = self.client.get(reverse('analysis-readings'), args).json()
        # The builder's sample values rise along the A-scan: the gate's highest sample is its last
        self.assertIn('A%', plain['readings'])
        louder = self.client.get(reverse('analysis-readings'), {**args, 'gain': 6}).json()
        self.assertAlmostEqual(louder['readings']['A%'] / plain['readings']['A%'], 10 ** (6 / 20), places=2)
        self.assertEqual(plain['gates']['A']['name'], 'A')

    def test_refuses_files_outside_and_bad_positions(self):
        outside = builders.weld_file(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, os.path.dirname(outside), True)
        for url, args in ((reverse('analysis-file'), {'path': outside}),
                          (reverse('analysis-frame'), {'path': self.weld, 'scan': 99}),
                          (reverse('analysis-frame'), {'path': self.weld, 'scan': 'x'}),
                          (reverse('analysis-readings'), {'path': self.weld, 'scan': 0, 'lateral': 9})):
            response = self.client.get(url, args)
            self.assertEqual(response.status_code, 400, (url, args))
            self.assertIn('error', response.json())

    def test_readings_with_the_editors_gates(self):
        args = {'path': self.weld, 'group': 0, 'scan': 1, 'lateral': 0}
        # The builder's samples rise along the A-scan (value = 1000 + sample): a later, shorter gate
        # ends on a higher sample, and a gate synced to A starts after A's crossing
        gates = [{'id': 1, 'name': 'Gate A', 'start': 4e-6, 'length': 5e-7, 'threshold': 1.0},
                 {'id': 2, 'name': 'Gate B', 'start': 2e-7, 'length': 1e-6, 'threshold': 1.0, 'sync_gate': 1}]
        data = self.client.get(reverse('analysis-readings'), {**args, 'gates': json.dumps(gates)}).json()
        a, b = data['gates']['A'], data['gates']['B']
        self.assertAlmostEqual(a['end'], 4.5e-6)
        self.assertAlmostEqual(b['start'], a['crossing_time'] + 2e-7)
        self.assertIn('B%', data['readings'])
        for bad in ('not json', json.dumps([{'id': 1, 'start': 0, 'length': -1, 'threshold': 20}])):
            self.assertEqual(self.client.get(reverse('analysis-readings'), {**args, 'gates': bad}).status_code, 400)
