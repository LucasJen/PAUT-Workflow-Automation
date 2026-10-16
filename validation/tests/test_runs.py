"""The kit's fingerprints, a whole run, and the page."""
import json
import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from analysis.tests import builders
from validation import runner
from validation.kit import Kit, KitError
from validation.models import ValidationRun, ValidationSettings


class KitRunTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.root = os.path.join(self.folder, 'kit')
        source = os.path.join(self.folder, 'source')
        os.makedirs(source)
        self.kit = Kit(self.root)
        self.weld = self.kit.add(builders.weld_file(source), ['decoding'], 'synthetic')
        self.raster = self.kit.add(builders.raster_file(source), ['decoding'], 'synthetic')

    def test_files_are_copied_in_and_fingerprinted(self):
        kit = Kit(self.root)
        self.assertEqual([e['path'] for e in kit.files], ['nde/weld.nde', 'nde/raster.nde'])
        self.assertTrue(all(c['ok'] for c in kit.verify()))
        with self.assertRaises(KitError):
            kit.add(os.path.join(self.folder, 'nothing.nde'), ['decoding'])
        with self.assertRaises(KitError):
            kit.add(kit.full_path(kit.files[0]), ['made-up role'])

    def test_a_clean_kit_passes(self):
        run = runner.execute(runner.create(['L0'], self.root))
        self.assertEqual(run.status, ValidationRun.PASSED, json.dumps(run.results)[:2000])
        self.assertEqual(run.failed, 0)
        self.assertGreater(run.passed, 0)
        self.assertTrue(run.manifest_sha)

    def test_a_changed_kit_file_fails_and_is_not_used(self):
        with open(self.kit.full_path(self.weld), 'ab') as f:
            f.write(b'\0')
        run = runner.execute(runner.create(['L0'], self.root))
        self.assertEqual(run.status, ValidationRun.FAILED)
        bad = [f for f in run.results['kit']['files'] if not f['ok']]
        self.assertEqual([f['path'] for f in bad], ['nde/weld.nde'])
        subjects = [c['subject'] for c in run.results['layers'][0]['checks']]
        self.assertFalse(any('weld.nde' in s for s in subjects))

    def test_unbuilt_layers_are_listed_not_run(self):
        run = runner.execute(runner.create(['L0', 'L2'], self.root))
        layer = run.results['layers'][1]
        self.assertEqual((layer['id'], layer['status']), ('L2', 'not built'))

    def test_a_missing_kit_is_an_error(self):
        run = runner.execute(runner.create(['L0'], os.path.join(self.folder, 'nowhere')))
        self.assertEqual(run.status, ValidationRun.ERROR)

    def test_the_page_starts_and_shows_a_run(self):
        settings = ValidationSettings.get()
        settings.kit_path = self.root
        settings.save()
        self.assertEqual(self.client.get(reverse('validation')).status_code, 200)
        with mock.patch.object(runner, 'start', runner.execute):
            response = self.client.post(reverse('validation-run-start'), json.dumps({'layers': ['L0']}), content_type='application/json')
        pk = response.json()['id']
        data = self.client.get(reverse('validation-run', args=[pk])).json()
        self.assertEqual(data['status'], 'passed')
        page = self.client.get(reverse('validation') + f'?run={pk}')
        self.assertContains(page, 'nde/weld.nde')
