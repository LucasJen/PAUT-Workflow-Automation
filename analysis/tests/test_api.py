import json
import os
import shutil
import time
import tempfile

import numpy as np
from django.test import TestCase, override_settings
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

    def test_whole_file_views_build_then_serve(self):
        with override_settings(ANALYSIS_CACHE_DIR=os.path.join(self.folder, '.cache')):
            args = {'path': self.weld, 'group': 0}
            response = self.client.get(reverse('analysis-cscan'), {**args, 'gate': 'A'})
            for _ in range(100):               # 409 while the background build runs
                if response.status_code != 409:
                    break
                time.sleep(0.05)
                response = self.client.get(reverse('analysis-cscan'), {**args, 'gate': 'A'})
            self.assertEqual((response['X-Scans'], response['X-Lines']), ('4', '3'))
            values = np.frombuffer(response.content, dtype='<f4').reshape(4, 3)
            self.assertTrue(np.isnan(values[0, 0]))          # no data there
            self.assertGreater(values[2, 1], 0)
            depth = np.frombuffer(self.client.get(reverse('analysis-cscan'), {**args, 'gate': 'A', 'kind': 'depth'}).content, dtype='<f4')
            self.assertTrue(np.all(depth[np.isfinite(depth)] <= 0.0125 + 1e-6))   # folded inside the 12.5 mm plate
            b = self.client.get(reverse('analysis-bscan'), {**args, 'line': 2})
            self.assertEqual((b['X-Scans'], b['X-Bins'], b['X-Factor']), ('4', '50', '1'))
            self.assertEqual(len(b.content), 4 * 50)
            self.assertEqual(self.client.get(reverse('analysis-projections'), args).json()['state'], 'done')
            self.assertEqual(self.client.get(reverse('analysis-cscan'), {**args, 'gate': 'Z'}).status_code, 400)

    def test_indications_saved_numbered_edited_exported_and_deleted(self):
        url = reverse('analysis-indications')
        body = {'path': self.weld, 'group': 0, 'scan': 2, 'lateral': 1, 'scan_position': 0.002, 'index_position': -0.0127,
                'angle': 55.0, 'readings': {'A%': 44.0, 'DA^': 0.00739, 'Length': 0.0254, 'U(m-r)': 0.002},
                'cursors': {'u_ref': 0.01}, 'sizing': {'method': '6'}}
        first = self.client.post(url, json.dumps(body), content_type='application/json').json()
        second = self.client.post(url, json.dumps({**body, 'scan': 3}), content_type='application/json').json()
        self.assertEqual((first['number'], second['number']), (1, 2))
        listed = self.client.get(url, {'path': self.weld}).json()['indications']
        self.assertEqual([i['scan'] for i in listed], [2, 3])
        edit = reverse('analysis-indication', args=[first['id']])
        changed = self.client.post(edit, json.dumps({'comment': 'Root lack of fusion'}), content_type='application/json')
        self.assertEqual(changed.json()['comment'], 'Root lack of fusion')
        csv_text = self.client.get(reverse('analysis-indications-csv'), {'path': self.weld}).content.decode('utf-8-sig')
        header, row = csv_text.splitlines()[:2]
        self.assertTrue(header.startswith('#,Group,Scan,Index,Angle,A%,DA^'))
        self.assertIn('44.000 %', row)
        self.assertIn('0.291 in', row)
        self.assertIn('1.000 in', row)
        self.assertIn('Root lack of fusion', row)
        self.client.delete(edit)
        self.assertEqual(len(self.client.get(url, {'path': self.weld}).json()['indications']), 1)
        outside = self.client.post(url, json.dumps({**body, 'path': 'C:/elsewhere/x.nde'}), content_type='application/json')
        self.assertEqual(outside.status_code, 400)

    def test_size_endpoint(self):
        with override_settings(ANALYSIS_CACHE_DIR=os.path.join(self.folder, '.cache')):
            from analysis.services import projections
            from analysis.services.nde_data import open_file
            group = open_file(self.weld).group(0)
            projections.ensure(self.weld, group, group.gates, background=False)
            data = self.client.get(reverse('analysis-size'), {'path': self.weld, 'scan': 2, 'lateral': 1, 'lines': 'all'}).json()
            self.assertIn('length', data)
            self.assertGreaterEqual(data['end'], data['start'])


class WeldOutlineApiTests(TestCase):
    def test_an_edited_weld_is_cleaned_and_drawn(self):
        weld = {'offset': 0.001, 'land': {'height': 0.0015}, 'fills': [{'angle': 37.5, 'height': 0.008}, {'angle': 'x'}],
                'upperCap': {'width': 0.016, 'height': 0.0015}, 'lowerCap': {'width': 1e9, 'height': -1}, 'evil': '<script>'}
        response = self.client.post(reverse('analysis-weld-outline'), json.dumps({'weld': weld, 'thickness': 0.0095}),
                                    content_type='application/json')
        data = response.json()
        self.assertNotIn('evil', data['weld'])
        self.assertEqual(data['weld']['lowerCap'], {'width': 0.5, 'height': 0.0})   # clamped: no root cap drawn
        self.assertEqual(data['weld']['fills'][1], {'angle': 0.0, 'height': 0.0})
        left, right, upper = data['lines']
        self.assertAlmostEqual(right[0][0], 0.001)
        self.assertAlmostEqual(right[-1][1], 0.0)
        bad = self.client.post(reverse('analysis-weld-outline'), json.dumps({'weld': weld}), content_type='application/json')
        self.assertEqual(bad.status_code, 400)
