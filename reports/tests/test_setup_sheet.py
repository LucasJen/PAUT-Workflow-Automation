"""The setup sheet: the .nde's whole setup as one picture under a setup's calibration data (setup_sheet.py)."""
import copy
import io
import json
import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse
from docxtpl import DocxTemplate
from PIL import Image

from reports.models import Report, Setup, SetupImage
from reports.services import setup_sheet
from reports.services.corrosion_report import corrosion_pages
from reports.services.nde_parser import extract_groups
from reports.services.report_render import _setup_context, template_path
from reports.tests.test_corrosion_report import picture
from reports.tests.test_nde_upload import FIXTURE, sample_setup


def fixture_sheet(setup=None):
    group = extract_groups(setup or sample_setup(), copy.deepcopy(FIXTURE['properties']), 'plate.nde')[0]
    return group['values']['imperial']['nde_sheet']


class SheetDataTests(TestCase):
    def test_the_file_setup_is_kept_in_si(self):
        data = json.loads(fixture_sheet())
        self.assertEqual(data['v'], 1)
        self.assertEqual(data['file'], 'plate.nde')
        self.assertIn('model', data['instrument'])
        self.assertTrue(data['probe']['model'])
        self.assertTrue(data['ut']['velocity'] > 1000)          # m/s
        self.assertEqual(json.loads(fixture_sheet()), json.loads(
            extract_groups(sample_setup(), copy.deepcopy(FIXTURE['properties']), 'plate.nde')[0]['values']['metric']['nde_sheet']))

    def test_each_focal_law_by_its_aperture_centre_and_angle(self):
        setup = sample_setup()
        ut = setup['groups'][0]['processes'][0]['ultrasonicPhasedArray']
        ut['beams'] = [{'refractedAngle': 0.0, 'pulsers': [{'elementId': i + k} for k in range(4)]} for i in range(3)]
        self.assertEqual(json.loads(fixture_sheet(setup))['beams'], [[1.5, 0.0], [2.5, 0.0], [3.5, 0.0]])
        png = setup_sheet.sheet_png(Setup(nde_sheet=fixture_sheet(setup)), 7.0, 6.0)
        self.assertEqual(png[1:4], b'PNG')

    def test_gates_name_their_synchro(self):
        setup = sample_setup()
        ut = setup['groups'][0]['processes'][0]['ultrasonicPhasedArray']
        ut['gates'] = [
            {'id': 0, 'name': 'Gate I', 'start': 1e-5, 'length': 1e-5, 'threshold': 40, 'synchronization': {'mode': 'Pulse'}},
            {'id': 1, 'name': 'Gate A', 'start': 2e-6, 'length': 8e-6, 'threshold': 20,
             'synchronization': {'mode': 'GateRelative', 'gateId': 0, 'triggeringEvent': 'Crossing'}},
        ]
        gates = json.loads(fixture_sheet(setup))['gates']
        self.assertEqual([(g['name'], g['synchro']) for g in gates], [('I', 'Pulse'), ('A', 'Gate I Crossing')])

    def test_a_video_filter_frequency_in_mhz(self):
        setup = sample_setup()
        setup['groups'][0]['processes'][0]['ultrasonicPhasedArray']['smoothingFilter'] = 7500000.0
        self.assertEqual(json.loads(fixture_sheet(setup))['ut']['smoothing'], '7.5 MHz')

    def test_sections_in_the_setups_units(self):
        data = json.loads(fixture_sheet())
        imperial = dict(setup_sheet.sections(data, 'imperial')[1][2])
        metric = dict(setup_sheet.sections(data, 'metric')[1][2])
        self.assertTrue(imperial['Velocity'].endswith('in/µs'))
        self.assertTrue(metric['Velocity'].endswith('m/s'))


class SheetPictureTests(TestCase):
    def test_laid_out_for_the_box(self):
        setup = Setup(nde_sheet=fixture_sheet())
        png = setup_sheet.sheet_png(setup, 7.0, 8.0)
        with Image.open(io.BytesIO(png)) as img:
            self.assertEqual(img.size, (2100, 2400))

    def test_tables_that_dont_fit_make_it_taller(self):
        with Image.open(io.BytesIO(setup_sheet.sheet_png(Setup(nde_sheet=fixture_sheet()), 7.0, 2.0))) as img:
            self.assertGreater(img.height, 600)

    def test_no_nde_no_sheet(self):
        self.assertIsNone(setup_sheet.sheet_png(Setup(), 7.0, 6.0))
        self.assertIsNone(setup_sheet.sheet_png(Setup(nde_sheet='not json'), 7.0, 6.0))

    def test_a_group_without_focal_laws_still_draws(self):
        data = json.loads(fixture_sheet())
        data.pop('beams', None)
        self.assertTrue(setup_sheet.sheet_png(Setup(nde_sheet=json.dumps(data)), 7.0, 6.0))


class SheetInReportsTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def setup_with_screenshot(self, report, sheet):
        setup = Setup.objects.create(report=report, title='HydroFORM', nde_sheet=sheet)
        SetupImage.objects.create(setup=setup, image=picture('cal.png'))
        return setup

    def test_long_form_prints_the_sheet_in_place_of_the_screenshots(self):
        report = Report.objects.create(report_type='paut_long')
        tpl = DocxTemplate(template_path(report))
        with_sheet = _setup_context(self.setup_with_screenshot(report, fixture_sheet()), 1, report, tpl)
        without = _setup_context(self.setup_with_screenshot(report, ''), 2, report, tpl)
        self.assertEqual(len(with_sheet['images']), 1)
        self.assertIsInstance(with_sheet['images'][0].image_descriptor, io.BytesIO)
        self.assertTrue(without['images'][0].image_descriptor.endswith('.png'))   # the screenshot

    def test_short_form_puts_the_sheet_in_the_picture_box(self):
        report = Report.objects.create(report_type='paut_corrosion')
        self.setup_with_screenshot(report, fixture_sheet())
        self.setup_with_screenshot(report, '')
        one, two = corrosion_pages(report).setups
        self.assertTrue(one.sheet.startswith(b'\x89PNG'))
        self.assertEqual(one.picture, '')
        self.assertIsNone(two.sheet)
        self.assertTrue(two.picture.endswith('.png'))

    def test_the_editor_keeps_the_sheet_when_saving(self):
        report = Report.objects.create(report_type='paut_long')
        Setup.objects.create(report=report, title='HydroFORM', nde_sheet=fixture_sheet())
        page = self.client.get(reverse('create-report'), {'loaded': report.pk})
        self.assertContains(page, 'name="setups-0-nde_sheet"')
