"""Probe / wedge catalogues, the sensitivity block table seed, and catalogue imports."""
import os
import unittest
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from equipment.forms import ProbeForm
from equipment.importers import CatalogueImportError, read_catalogue_file
from equipment.models import Probe, ProbeModel, SensitivityBlock, WedgeModel

SAMPLE_NDE = os.path.join(settings.BASE_DIR, 'outputs', '11v9 boot 12x12 trace obs.nde')


class SeedTests(TestCase):
    """The migrations load the Evident catalogue data and the reference Cal Block Table."""

    def test_probe_catalogue(self):
        probe = ProbeModel.objects.get(model='10L32-A1')
        self.assertEqual((probe.series, probe.elements, probe.pitch, probe.elevation), ('A1', 32, 0.31, 7.0))
        for series in ('A1', 'A2', 'A10', 'A15', 'A31', 'A32'):
            self.assertTrue(ProbeModel.objects.filter(series=series).exists(), series)

    def test_wedge_catalogue(self):
        wedge = WedgeModel.objects.get(model='SA1-N60S')
        self.assertEqual((wedge.refracted_angle, wedge.wave_type, wedge.length, wedge.height), (60, 'SW', 30, 16))
        self.assertEqual((wedge.wedge_angle, wedge.first_element_height), (38.9, 8.382))
        self.assertFalse(wedge.has_geometry)  # velocity / primary offset still to import

    def test_block_table(self):
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        self.assertEqual((block.serial_number, block.test_thickness, block.test_diameter, block.bevel_geometry),
                         ('19019', '0.280', '6.625"', '37 degrees'))
        self.assertEqual(SensitivityBlock.objects.exclude(pipe_size='').count(), 26)


class CatalogueImportTests(TestCase):
    def test_unsupported_file(self):
        with self.assertRaisesMessage(CatalogueImportError, 'not a supported file'):
            read_catalogue_file(SimpleUploadedFile('wedges.csv', b'x'))

    @mock.patch('equipment.catalogue_views.read_catalogue_file')
    def test_import_adds_and_updates(self, read):
        read.return_value = (
            [{'model': '10L32-A1', 'pitch': 0.31}, {'model': 'NEW-PROBE', 'pitch': 1.0}],
            [{'model': 'SA1-N60S', 'velocity': 2330.0, 'primary_offset': -12.5}],
        )
        resp = self.client.post(reverse('import-catalogue'), {
            'next': 'wedge-model-list', 'file': SimpleUploadedFile('a.nde', b'x'),
        }, follow=True)
        self.assertContains(resp, 'added NEW-PROBE')
        self.assertContains(resp, '10L32-A1 already up to date')
        self.assertContains(resp, 'updated SA1-N60S')
        wedge = WedgeModel.objects.get(model='SA1-N60S')
        self.assertEqual((wedge.velocity, wedge.primary_offset), (2330.0, -12.5))
        self.assertTrue(wedge.has_geometry)

    def test_import_only_returns_to_catalogue_pages(self):
        resp = self.client.post(reverse('import-catalogue'), {'next': 'https://example.com'})
        self.assertRedirects(resp, reverse('wedge-model-list'))

    @unittest.skipUnless(os.path.exists(SAMPLE_NDE), 'sample .nde not present')
    def test_reads_probe_and_wedge_from_nde(self):
        with open(SAMPLE_NDE, 'rb') as f:
            probes, wedges = read_catalogue_file(SimpleUploadedFile('scan.nde', f.read()))
        self.assertEqual(probes[0]['model'], '7.5L64-I4')
        self.assertEqual((probes[0]['pitch'], probes[0]['elevation']), (1.0, 7.0))
        self.assertEqual(wedges[0]['model'], 'HydroFORM')
        self.assertEqual((wedges[0]['primary_offset'], wedges[0]['first_element_height']), (-71.0, 13.0))


class CataloguePageTests(TestCase):
    def test_pages(self):
        for name in ('probe-model-list', 'wedge-model-list', 'new-probe-model', 'new-wedge-model'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        wedge = WedgeModel.objects.get(model='SA1-N60S')
        self.assertContains(self.client.get(reverse('edit-wedge-model', args=[wedge.pk])), 'Geometry for the scan plan')

    def test_create_probe_model(self):
        resp = self.client.post(reverse('new-probe-model'), {'model': '5L32-TEST', 'pitch': '0.5', 'manufacturer': 'Evident'})
        item = ProbeModel.objects.get(model='5L32-TEST')
        self.assertRedirects(resp, reverse('edit-probe-model', args=[item.pk]))

    def test_inventory_probe_takes_details_from_its_model(self):
        model = ProbeModel.objects.get(model='10L32-A1')
        form = ProbeForm({'catalogue': model.pk, 'serial_number': 'Y2037'})
        self.assertTrue(form.is_valid(), form.errors)
        probe = form.save()
        self.assertEqual((probe.model, probe.frequency, probe.elements, probe.manufacturer),
                         ('10L32-A1', '10 MHz', '32', 'Evident'))
        self.assertEqual(Probe.objects.get().catalogue, model)
