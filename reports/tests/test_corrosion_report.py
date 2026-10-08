"""The corrosion form (598-PAUTFORM-009): what goes on which page (corrosion_report.corrosion_pages)."""
import shutil
import tempfile
from datetime import date
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from reports.models import Report, ReportImage, Setup, SetupImage
from reports.report_types import get_report_type
from reports.services.corrosion_report import HORIZONTAL, VERTICAL, corrosion_pages, method_name


def picture(name, size=(400, 300)):
    buf = BytesIO()
    Image.new('RGB', size, 'white').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class CorrosionPagesTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.report = Report.objects.create(
            report_type='paut_corrosion', item_description='Phased Array Ultrasonic Examinations on Selected Areas On Ammonia Vaporizer 11V58A', equipment_id='11V58A',
            client='Flint Hills Resources', location='Rosemount, MN', work_order='WO5382118',
            test_date=date(2026, 3, 11), procedure='100-UT-031', procedure_rev='1',
            weld_technician='Lucas Jennings', weld_technician_cert='PAUT Level II',
            examination_scope='Manual 0 degree UT on the shell and heads.', executive_summary='No corrosion.',
            notes='See drawing.')

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_the_type_is_an_excel_form_with_its_own_guided_steps(self):
        rtype = get_report_type('paut_corrosion')
        self.assertEqual((rtype.output_format, rtype.template, rtype.guided), ('xlsx', 'paut_corrosion.xlsx', True))
        self.assertEqual(rtype.wizard_last_step, 'images')
        self.assertIn('scan_id', rtype.hidden_fields)
        self.assertNotIn('inspection_material', rtype.hidden_fields)
        # The setup's procedure is hidden, not the report's
        self.assertIn('setup.procedure', rtype.hidden_fields)
        self.assertNotIn('procedure', rtype.hidden_fields)
        self.assertIn('inspection_material', get_report_type('paut_long').hidden_fields)

    def test_summary_page(self):
        pages = corrosion_pages(self.report)
        s = pages.summary
        self.assertEqual(s['B2'], 'Phased Array Ultrasonic Examinations on Selected Areas On Ammonia Vaporizer 11V58A')
        self.assertEqual((s['L5'], s['L6'], s['L7'], s['AC7']), ('Flint Hills Resources', 'Rosemount, MN', 'WO5382118', '11V58A'))
        self.assertEqual((s['AA6'], s['AH6'], s['AA5']), ('100-UT-031', '1', date(2026, 3, 11)))
        self.assertEqual(s['AJ5'], date.today())   # no report date: today, as the form's =TODAY() would
        self.assertEqual(s['I8'], 'Lucas Jennings\nPAUT Level II')
        self.assertEqual(s['AC8'], '')
        self.assertEqual((s['B11'], s['B18'], s['B43']), ('Manual 0 degree UT on the shell and heads.', 'No corrosion.', 'See drawing.'))
        self.assertEqual((pages.page_count, s['AO6']), (1, '1'))

    def test_a_setup_page_per_setup_with_its_first_image(self):
        first = Setup.objects.create(report=self.report, order=0, title='hydroform', surface_prep='Wire brushed',
                                     material_temp='72 °F', tr_min='0.250', tr_max='0.625', inspection_material='SA-516-70',
                                     inspection_temp='80 °F', scope_model='OmniScan X3', scope_serial='QC-1',
                                     cal_material='Carbon Steel', cal_block_type='10-Step', cal_block_serial='51351',
                                     transducer_model='Olympus D791', transducer_serial='1009752')
        SetupImage.objects.create(setup=first, image=picture('cal.png'), order=1)
        SetupImage.objects.create(setup=first, image=picture('first.png'), order=0)
        Setup.objects.create(report=self.report, order=1, title='Shear-wave special')
        pages = corrosion_pages(self.report)
        one, two = pages.setups
        self.assertEqual(one.cells, {
            'AG2': 'HydroFORM', 'J7': 'Wire brushed', 'Z7': '72 °F', 'AJ7': '0.250', 'AN7': '0.625',
            'J8': 'SA-516-70', 'Z8': '80 °F', 'AH8': 'OmniScan X3\nSN: QC-1', 'L9': 'Carbon Steel 10-Step\nSN: 51351',
            'AB9': 'Olympus D791\nSN: 1009752'})
        self.assertTrue(one.method_known)
        self.assertTrue(one.picture.endswith('first.png'))
        self.assertEqual((two.cells['AG2'], two.method_known, two.picture), ('Shear-wave special', False, ''))
        self.assertEqual(pages.summary['AO6'], '3')

    def test_drawings_by_shape_and_images_two_to_a_page(self):
        ReportImage.objects.create(report=self.report, kind='drawing', image=picture('wide.png', (800, 600)), order=0)
        ReportImage.objects.create(report=self.report, kind='drawing', image=picture('tall.png', (600, 800)), order=1)
        for i in range(3):
            ReportImage.objects.create(report=self.report, kind='scan', image=picture(f's{i}.png'), order=i,
                                       caption=f'Scan {i}', description=f'Lowest 0.3{i}"')
        pages = corrosion_pages(self.report)
        self.assertEqual([sheet for sheet, _ in pages.drawings], [HORIZONTAL, VERTICAL])
        self.assertEqual([[(slot.caption, slot.description) for slot in page] for page in pages.images],
                         [[('Scan 0', 'Lowest 0.30"'), ('Scan 1', 'Lowest 0.31"')], [('Scan 2', 'Lowest 0.32"')]])
        self.assertEqual(pages.page_count, 1 + 2 + 2)

    def test_method_names_match_the_forms_list(self):
        self.assertEqual(method_name(' manual ut '), 'Manual UT')
        self.assertEqual(method_name('fmc / tfm'), 'FMC / TFM')
        self.assertEqual(method_name('Phased array'), '')
