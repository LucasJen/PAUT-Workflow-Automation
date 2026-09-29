import copy
import io
import json
from pathlib import Path

import h5py
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'nde_linear_plate_raster.json').read_text(encoding='utf-8'))


def sample_setup():
    """Metadata from a real MXU raster scan (trimmed, serial anonymised)."""
    return copy.deepcopy(FIXTURE['setup'])


def make_nde(setup, properties=None, as_bytes=True):
    buf = io.BytesIO()
    with h5py.File(buf, 'w') as f:
        payload = json.dumps(setup)
        f['Public/Setup'] = payload.encode('utf-8') if as_bytes else payload
        if properties is not None:
            f['Properties'] = json.dumps(properties).encode('utf-8')
    return buf.getvalue()


class NdeUploadTests(TestCase):
    url = reverse('nde-upload')

    def upload(self, content, name='scan.nde'):
        return self.client.post(self.url, {'nde_file': SimpleUploadedFile(name, content)})

    def test_parses_groups(self):
        resp = self.upload(make_nde(sample_setup(), FIXTURE['properties']))
        groups = resp.context['nde_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['values']['imperial']['scope_model'], 'OmniScan X3 64 - 64:128PR')
        self.assertEqual(groups[0]['values']['imperial']['source_file'], 'scan.nde')
        self.assertContains(resp, 'id="nde-groups"')

    def test_parses_str_dataset(self):
        resp = self.upload(make_nde(sample_setup(), as_bytes=False))
        self.assertEqual(len(resp.context['nde_groups']), 1)

    def test_uppercase_extension_accepted(self):
        resp = self.upload(make_nde(sample_setup()), name='SCAN.NDE')
        self.assertNotIn('error', resp.context)

    def test_file_content_cannot_break_out_of_script(self):
        setup = sample_setup()
        setup['probes'][0]['model'] = '</script><script>alert(1)</script>'
        resp = self.upload(make_nde(setup))
        self.assertNotContains(resp, '<script>alert(1)</script>')

    def test_missing_setup_reports_error(self):
        buf = io.BytesIO()
        with h5py.File(buf, 'w') as f:
            f['Other'] = 1
        resp = self.upload(buf.getvalue())
        self.assertIn('No Setup metadata', resp.context['error'])

    def test_not_hdf5_reports_error(self):
        resp = self.upload(b'not an hdf5 file')
        self.assertIn('Failed to parse file', resp.context['error'])

    def test_file_without_groups_reports_error(self):
        resp = self.upload(make_nde({'version': '4.1.0', 'groups': []}))
        self.assertIn('no inspection groups', resp.context['error'])

    def test_multiple_groups_show_picker(self):
        setup = sample_setup()
        second = copy.deepcopy(setup['groups'][0])
        second['id'], second['name'] = 1, 'GR-2'
        setup['groups'].append(second)
        resp = self.upload(make_nde(setup))
        self.assertContains(resp, 'id="nde-group"')
        self.assertContains(resp, 'GR-2 · Linear · 0°')
