"""Probe / wedge catalogues, the sensitivity block table seed, and catalogue imports."""
import io
import os
import tempfile
import unittest
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from equipment.forms import ProbeForm
from django.core.management import call_command

from equipment.compat import fit_tokens, probe_token, wedge_fits_probe
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
        self.assertEqual((wedge.wedge_angle, wedge.first_element_height), (38.9, None))  # see migration 0008
        self.assertFalse(wedge.has_geometry)  # velocity / primary offset still to import

    def test_block_table(self):
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        self.assertEqual((block.serial_number, block.test_thickness, block.test_diameter, block.bevel_geometry),
                         ('19019', '0.280', '6.625"', '37 degrees'))
        self.assertEqual(SensitivityBlock.objects.exclude(pipe_size='').count(), 26)


class CatalogueImportTests(TestCase):
    def test_unsupported_file(self):
        with self.assertRaisesMessage(CatalogueImportError, 'not a supported file'):
            read_catalogue_file(SimpleUploadedFile('wedges.txt', b'x'))

    @mock.patch('equipment.catalogue_views.read_catalogue_file')
    def test_import_adds_and_updates(self, read):
        read.return_value = (
            [{'model': '10L32-A1', 'pitch': 0.31}, {'model': 'NEW-PROBE', 'pitch': 1.0}],
            [{'model': 'SA1-N60S', 'velocity': 2330.0, 'primary_offset': -12.5, 'first_element_height': 5.0}],
        )
        resp = self.client.post(reverse('import-catalogue'), {
            'next': 'wedge-model-list', 'file': SimpleUploadedFile('a.nde', b'x'),
        }, follow=True)
        self.assertContains(resp, '1 probe model added (NEW-PROBE)')
        self.assertContains(resp, '1 probe model already up to date (10L32-A1)')
        self.assertContains(resp, '1 wedge model updated (SA1-N60S)')
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


PROBES_CSV = b"""Manufacturer,PartNo,TotalElements,ElementPitch,ElementWidth,ElementPassiveWidth,Linked,Frequency,Axis2NumElements,Axis2Pitch,ElementPattern,DateAdded
Olympus,10L32-A1,32,0.31,,7.0,0,10.0,1,,,
Evident,10L32-A1,32,0.31,,7.0,0,10.0,1,,,2024-07-24
Doppler,10L16-0.6*10-B56,16,0.6,,10.0,0,10.0,,,,
"""

WEDGES_CSV = b"""Manufacturer,PartNo,Angle,Height,Length,X,Xt,Z,W,Y,Inset,InsetBuffer,Velocity,Linked,FrontSlope,HighTemp,HighTempfnExitDelta,HighTempfnExitDeflection,InsetBufferSide,RoofAngle,Yt,YPos,SquintAngle,WedgeType,BottomFaceShape,PartDiameter,DateAdded
Olympus,SA1-N60S 10L32,39.0,16.4,30.4,27.0,3.4,5.0,30.0,15.0,0.0,0.0,2330.0,0,0.0,0,,,0,,,,,,,,
Evident,SA1-N60S 10L32,39.0,16.41,30.38,27.19,3.19,5.15,30.0,15.0,0.0,0.0,2330.0,0,0.0,0,,,,,,,,,,,2024-07-24
Evident,SA10-N55S 5/10L32,36.1,14.22,23.02,20.58,2.44,6.78,23.0,11.5,0.0,0.0,2330.0,0,0.0,0,,,,,,,,,AOD,114.3,2024-07-24
Olympus,ABWX1249_5L16-A1,42.5,28.0,52.9,35.6,17.3,18.9,50.0,25.0,0.0,0.0,2330.0,0,0.0,0,,,,,,,,,,,
Evident,ABWX122A,30.0,20.0,40.0,30.0,10.0,8.0,30.0,15.0,0.0,0.0,2330.0,0,0.0,0,,,,,,,,,,,2024-07-24
Zetec,AS - 55SW,36.0,10.2,16.3,14.52,1.78,5.0,30.0,15.0,0.0,0.0,2330.0,0,0.0,0,,,,,,,,,,,
"""


class BeamtoolImportTests(TestCase):
    def wedges(self):
        _, wedges = read_catalogue_file(SimpleUploadedFile('PAWedges.csv', WEDGES_CSV))
        return {w['model']: w for w in wedges}

    def test_probes(self):
        probes, wedges = read_catalogue_file(SimpleUploadedFile('PATransducers.csv', PROBES_CSV))
        self.assertEqual(wedges, [])
        by_model = {p['model']: p for p in probes}
        self.assertEqual(len(probes), 2)  # the Olympus and Evident rows of one part are one entry
        self.assertEqual(by_model['10L32-A1']['manufacturer'], 'Evident')
        self.assertEqual((by_model['10L32-A1']['pitch'], by_model['10L32-A1']['elevation']), (0.31, 7.0))
        self.assertEqual(by_model['10L32-A1']['series'], 'A1')

    def test_wedge_geometry(self):
        wedge = self.wedges()['SA1-N60S 10L32']
        self.assertEqual(wedge['manufacturer'], 'Evident')  # the newer Evident row wins
        self.assertEqual((wedge['wedge_angle'], wedge['velocity'], wedge['primary_offset'], wedge['first_element_height']),
                         (39.0, 2330.0, -27.19, 5.15))
        self.assertEqual((wedge['length'], wedge['height'], wedge['width']), (30.38, 16.41, 30.0))
        self.assertEqual((wedge['probe_series'], wedge['probe_fit'], wedge['refracted_angle'], wedge['wave_type']),
                         ('A1', '10L32', 60.0, 'SW'))

    def test_wedge_names(self):
        wedges = self.wedges()
        self.assertEqual((wedges['SA10-N55S 5/10L32']['bottom_face'], wedges['SA10-N55S 5/10L32']['part_diameter']),
                         ('AOD', 114.3))
        self.assertEqual(wedges['ABWX1249_5L16-A1']['probe_series'], 'A1')
        self.assertEqual(wedges['AS - 55SW']['refracted_angle'], 55.0)
        self.assertNotIn('probe_series', wedges['AS - 55SW'])

    def test_command_imports_both_files(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name, content in (('PATransducers.csv', PROBES_CSV), ('PAWedges.csv', WEDGES_CSV)):
                paths.append(os.path.join(folder, name))
                with open(paths[-1], 'wb') as f:
                    f.write(content)
            call_command('import_catalogue', *paths, stdout=io.StringIO())
        wedge = WedgeModel.objects.get(model='SA1-N60S 10L32')
        self.assertTrue(wedge.has_geometry)
        self.assertEqual(wedge.source, 'ES Beamtool library')
        probe = ProbeModel.objects.get(model='10L32-A1')
        self.assertTrue(probe.source.startswith('Evident PA probe catalogue'))  # keeps its own source
        self.assertTrue(ProbeModel.objects.filter(model='10L16-0.6*10-B56', manufacturer='Doppler').exists())


class WedgeFitTests(TestCase):
    def test_tokens(self):
        self.assertEqual(probe_token('10L32-A1'), '10L32')
        self.assertEqual(probe_token('7.5CCEV35-A15'), '7.5CCEV35')
        self.assertEqual(fit_tokens('5/10L32'), ({'5L32', '10L32'}, set()))
        self.assertEqual(fit_tokens('10L32R'), ({'10L32'}, set()))
        self.assertEqual(fit_tokens('10L32-A10'), ({'10L32'}, set()))
        self.assertEqual(fit_tokens('2.25-3-5'), (set(), {2.25, 3.0, 5.0}))

    def fits(self, wedge, probe='10L32-A1'):
        defaults = dict(manufacturer='Evident', probe_series='A1', probe_fit='', source='ES Beamtool library')
        return wedge_fits_probe(WedgeModel(**{**defaults, **wedge}), ProbeModel.objects.get(model=probe))

    def test_matching(self):
        self.assertTrue(self.fits({'probe_fit': '10L32'}))
        self.assertTrue(self.fits({'probe_fit': '5/10L32'}))
        self.assertFalse(self.fits({'probe_fit': '5L16'}))
        self.assertFalse(self.fits({'probe_series': 'A2', 'probe_fit': '10L32'}))
        self.assertFalse(self.fits({'manufacturer': 'Doppler'}))
        self.assertTrue(self.fits({'manufacturer': 'Olympus'}))                    # same family
        self.assertFalse(self.fits({'probe_series': '', 'probe_fit': ''}))          # library wedge, no clue
        self.assertTrue(self.fits({'probe_series': '', 'source': ''}))              # entered by hand
        self.assertTrue(self.fits({'probe_series': 'A15', 'probe_fit': '2.25-3-5'}, '5CCEV35-A15'))
        self.assertFalse(self.fits({'probe_series': 'A15', 'probe_fit': '2.25-3-5'}, '7.5CCEV35-A15'))
