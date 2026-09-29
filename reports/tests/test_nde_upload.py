import io
import json

import h5py
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse


def make_nde(setup, as_bytes=True):
    buf = io.BytesIO()
    with h5py.File(buf, 'w') as f:
        payload = json.dumps(setup)
        f['Public/Setup'] = payload.encode('utf-8') if as_bytes else payload
    return buf.getvalue()


class NdeUploadTests(TestCase):
    url = reverse('nde-upload')

    def upload(self, content, name='scan.nde'):
        return self.client.post(self.url, {'nde_file': SimpleUploadedFile(name, content)})

    def test_parses_setup_json(self):
        resp = self.upload(make_nde({'version': '4.0.0'}))
        self.assertEqual(resp.context['setup_data'], {'version': '4.0.0'})

    def test_parses_str_dataset(self):
        resp = self.upload(make_nde({'version': '4.0.0'}, as_bytes=False))
        self.assertEqual(resp.context['setup_data'], {'version': '4.0.0'})

    def test_uppercase_extension_accepted(self):
        resp = self.upload(make_nde({'version': '4.0.0'}), name='SCAN.NDE')
        self.assertNotIn('error', resp.context)

    def test_file_content_cannot_break_out_of_script(self):
        resp = self.upload(make_nde({'model': '</script><script>alert(1)</script>'}))
        self.assertNotContains(resp, '<script>alert(1)</script>')

    def test_missing_setup_reports_error(self):
        buf = io.BytesIO()
        with h5py.File(buf, 'w') as f:
            f['Other'] = 1
        resp = self.upload(buf.getvalue())
        self.assertIn('No Setup metadata', resp.context['error'])
