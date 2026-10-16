"""
L0 on synthetic files: clean files pass, and every kind of planted error is caught - a validator that
can't fail proves nothing.
"""
import json
import shutil
import tempfile
from unittest import mock

import h5py
import numpy as np
from django.test import SimpleTestCase

from analysis.services import nde_data
from analysis.tests import builders
from validation.checks import decoding


def failures(checks):
    return [(c['subject'], i['what'], i['measured']) for c in checks if c['kind'] == 'check' for i in c['items'] if not i['ok']]


class DecodingTests(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_clean_files_of_every_layout_pass(self):
        for make in (builders.weld_file, builders.raster_file, builders.conventional_file):
            checks = decoding.check_file(make(self.folder), seed=1)
            with self.subTest(make.__name__):
                self.assertTrue(checks)
                self.assertEqual(failures(checks), [])
                samples = next(i for i in checks[0]['items'] if i['what'].startswith('Raw samples'))
                self.assertIn('0 differ', samples['measured'])

    def test_a_group_without_a_scans_is_listed_not_passed(self):
        checks = decoding.check_file(builders.tfm_file(self.folder), seed=1)
        self.assertEqual([c['kind'] for c in checks], ['info'])

    def test_a_changed_sample_is_caught_with_where_it_is(self):
        real = nde_data.read_frame

        def corrupt(path, group, scan):
            amplitudes, status = real(path, group, scan)
            amplitudes = amplitudes.copy()
            amplitudes[1, 7] += 1
            return amplitudes, status
        path = builders.weld_file(self.folder)
        with mock.patch.object(nde_data, 'read_frame', corrupt):
            bad = failures(decoding.check_file(path, seed=1))
        self.assertTrue(any('Raw samples' in what and 'line 1, sample 7' in measured for _, what, measured in bad), bad)

    def test_a_wrong_scale_to_percent_is_caught(self):
        path = builders.weld_file(self.folder)
        with mock.patch.object(nde_data, 'to_unit', lambda raw, group: np.asarray(raw, dtype=np.float32) * (100.0 / group.raw_max)):
            bad = failures(decoding.check_file(path, seed=1))
        self.assertTrue(any('% of full screen' in what for _, what, _ in bad), bad)

    def test_a_beam_angle_read_wrong_is_caught(self):
        path = builders.weld_file(self.folder)
        real = nde_data.open_file

        def tilted(p):
            info = real(p)
            info.groups[0].beams[2].refracted_angle += 0.5
            return info
        with mock.patch.object(nde_data, 'open_file', tilted):
            bad = failures(decoding.check_file(path, seed=1))
        self.assertTrue(any('beam 2 refractedAngle' in measured for _, _, measured in bad), bad)

    def test_samples_stored_wider_than_the_app_reads_are_caught(self):
        # A file storing unsigned 16-bit samples above 32767: read as int16 they'd wrap negative
        path = builders.weld_file(self.folder)
        with h5py.File(path, 'r+') as h5:
            name = 'Public/Groups/0/Datasets/0-AScanAmplitude'
            data = h5[name][()].astype(np.uint16) + 40000
            del h5[name]
            h5.create_dataset(name, data=data, chunks=(1,) + data.shape[1:])
            setup = json.loads(h5['Public/Setup'][()])
            setup['groups'][0]['datasets'][0]['dataValue']['max'] = 65535
            del h5['Public/Setup']
            h5.create_dataset('Public/Setup', data=json.dumps(setup).encode())
        bad = failures(decoding.check_file(path, seed=1))
        self.assertTrue(any('Raw samples' in what for _, what, _ in bad), bad)

    def test_the_frames_compared_are_the_ends_the_middle_and_two_fixed_picks(self):
        frames = decoding.frames_to_compare(100, seed=7)
        self.assertEqual(frames, decoding.frames_to_compare(100, seed=7))
        self.assertTrue({0, 50, 99} <= set(frames))
        self.assertEqual(decoding.frames_to_compare(1, seed=7), [0])
