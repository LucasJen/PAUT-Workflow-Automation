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


class SheetEditsTests(TestCase):
    """The Setup values table's changes: kept beside the file's values, used when the picture is drawn."""

    def test_edits_replace_the_files_values_and_the_file_stays(self):
        data = json.loads(fixture_sheet())
        data['gates'] = [{'name': 'A', 'start': 2e-6, 'length': 8e-6, 'threshold': 20}]
        data['edits'] = {'part.thickness': 0.0254, 'ut.velocity': 3000.0, 'gates.0.threshold': 35,
                         'instrument.model': 'OmniScan X4', 'part.od': '', 'evil.__class__': 1, 'gates.9.start': 1}
        setup = Setup(nde_sheet=json.dumps(data))
        loaded = setup_sheet.load(setup)
        self.assertEqual(loaded['part']['thickness'], 0.0254)
        self.assertEqual(loaded['ut']['velocity'], 3000.0)
        self.assertEqual(loaded['gates'][0]['threshold'], 35)
        self.assertEqual(loaded['instrument']['model'], 'OmniScan X4')
        self.assertNotIn('od', loaded['part'])                  # a blank edit takes the value off
        self.assertNotIn('edits', loaded)
        self.assertNotIn('evil', loaded)                        # paths are plain names only... and harmless
        self.assertEqual(len(loaded['gates']), 1)               # a gate that isn't there isn't made
        self.assertEqual(json.loads(setup.nde_sheet)['ut']['velocity'], data['ut']['velocity'])   # stored as the file gave it
        velocity = dict(setup_sheet.sections(loaded, 'metric')[1][2])['Velocity']
        self.assertEqual(velocity, '3000 m/s')
        self.assertTrue(setup_sheet.sheet_png(setup, 7.0, 6.0).startswith(b'\x89PNG'))

    def test_the_schema_names_every_editable_value_and_its_report_field(self):
        schema = setup_sheet.editable_schema()
        rows = {r['path']: r for s in schema for r in s['rows']}
        self.assertEqual(rows['part.thickness']['field'], 'specimen_thickness')
        self.assertEqual(rows['ut.velocity']['kind'], 'velocity')
        self.assertTrue(all(field in {f.name for f in Setup._meta.fields} for field in (r['field'] for r in rows.values()) if field))

    def test_preview_draws_the_picture_with_the_changes(self):
        data = json.loads(fixture_sheet())
        data['edits'] = {'part.thickness': 0.03}
        response = self.client.post(reverse('setup-sheet-preview'), {'nde_sheet': json.dumps(data), 'units': 'imperial',
                                                                     'specimen_thickness': '1.181', 'report_type': 'paut_corrosion'})
        self.assertEqual(response['Content-Type'], 'image/png')
        with Image.open(io.BytesIO(response.content)) as img:
            self.assertEqual(img.size, (int(7.6 * 300), int(7.2 * 300)))   # the Short Form's picture box
        self.assertEqual(self.client.post(reverse('setup-sheet-preview'), {'nde_sheet': ''}).status_code, 400)

    def test_the_editor_has_the_table_and_its_schema(self):
        report = Report.objects.create(report_type='paut_corrosion')
        Setup.objects.create(report=report, title='HydroFORM', nde_sheet=fixture_sheet())
        page = self.client.get(reverse('create-report'), {'loaded': report.pk})
        self.assertContains(page, 'data-setup-values')
        self.assertContains(page, 'id="setup-values-schema"')
        self.assertContains(page, 'setup_values.js')


class SheetWeldTests(TestCase):
    """The Weld & offsets panel: the weld drawn on the setup picture's scan plan at each offset."""

    def test_the_weld_and_its_offsets_from_the_setup(self):
        setup = Setup(weld_on=False, weld_bevel_angle='30')
        self.assertIsNone(setup_sheet.weld_spec(setup))                 # off: no weld
        setup = Setup(weld_on=True, units='metric', weld_bevel_angle='30', weld_root_face='2.54', weld_root_gap='',
                      index_offset='12.7', extra_offsets='25.4, x, 38.1')
        weld = setup_sheet.weld_spec(setup)
        self.assertEqual(weld['angle'], 30.0)
        self.assertAlmostEqual(weld['face'], 0.1)
        self.assertEqual(weld['gap'], 0.0)
        self.assertEqual([round(o, 3) for o in weld['offsets']], [0.5, 1.0, 1.5])   # mm to inches; nonsense skipped
        self.assertEqual(setup_sheet.weld_spec(Setup(weld_on=True, weld_bevel_angle=''))['offsets'], [None])

    def test_several_offsets_still_one_picture_the_boxs_size(self):
        base = dict(nde_sheet=fixture_sheet(), weld_on=True, weld_bevel_angle='30', weld_root_face='0.06',
                    weld_root_gap='0.1', index_offset='0.5')
        for extra in ('', '1.0', '1.0, 1.5, 2.0'):
            png = setup_sheet.sheet_png(Setup(**base, extra_offsets=extra), 7.6, 7.2)
            with Image.open(io.BytesIO(png)) as img:
                self.assertEqual(img.size, (2280, 2160), extra)
        # The weld is in the drawing: its centre line the offset ahead of the wedge front
        data = setup_sheet.load(Setup(**base))
        weld = setup_sheet.weld_spec(Setup(**base))
        scene = setup_sheet.drawing_scene(data, Setup(**base), 0.5, 'imperial', 1500, weld=weld, weld_offset=0.5)
        polygons = [s for s in scene.shapes if s['kind'] == 'polygon' and s.get('fill') == 'weld']
        self.assertEqual(len(polygons), 2)                               # the V and its cap
        front = -setup_sheet._inch(data['wedge']['primary_offset'])
        xs = [x for x, _ in polygons[0]['points']]
        self.assertAlmostEqual((min(xs) + max(xs)) / 2, front + 0.5, places=6)

    def test_the_import_takes_the_bevel_from_the_pass_with_a_height(self):
        from reports.services.nde_parser import extract_groups
        from reports.tests.test_scan_plans import WELD_SETUP
        setup = copy.deepcopy(WELD_SETUP)
        weld = setup['specimens'][0]['weldGeometry']
        weld['fills'] = [{'angle': 0.0, 'height': 0.0}]
        weld['hotPass'] = {'angle': 30.0, 'height': 0.0056}
        self.assertEqual(extract_groups(setup)[0]['values']['imperial']['weld_bevel_angle'], '30')

    def test_the_editor_shows_the_panel_and_the_short_form_shows_its_fields(self):
        from reports.report_types import REPORT_TYPES
        report = Report.objects.create(report_type='paut_corrosion')
        Setup.objects.create(report=report, nde_sheet=fixture_sheet(), weld_on=True, index_offset='0.5', extra_offsets='1.0')
        page = self.client.get(reverse('create-report'), {'loaded': report.pk})
        self.assertContains(page, 'data-setup-weld')
        self.assertContains(page, 'name="setups-0-extra_offsets"')
        self.assertContains(page, 'name="setups-0-weld_on"')
        hidden = REPORT_TYPES['paut_corrosion'].hidden_fields
        for name in ('weld_on', 'weld_bevel_angle', 'index_offset', 'extra_offsets'):
            self.assertNotIn(f'setup.{name}', hidden)
