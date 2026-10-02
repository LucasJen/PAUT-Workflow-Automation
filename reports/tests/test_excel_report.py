"""Excel weld report: the cell map, the views, and (optionally) a real Excel run."""
import datetime
import os
import tempfile
import unittest
from unittest import mock

from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from equipment.models import SensitivityBlock
from reports.models import Report, ReportImage, ReportPerson, ResultsRow, ResultsTable, ScanPlan, Setup
from reports.report_types import get_report_type
from reports.services import excel_report
from reports.services.excel_report import CHECK, CROSS, weld_pages

FAKE_XLSX = b'PK fake xlsx'
FAKE_PDF = b'%PDF-1.7 fake'


def weld_row(weld='W5', flaw='', verdict='Accept', notes='Passes per B31.3'):
    cells = [''] * 18
    cells[0], cells[1], cells[7] = weld, 'RJA4201', '0.280'
    cells[15], cells[16], cells[17] = flaw, verdict, notes
    return cells


def weld_report(rows=(), **fields):
    report = Report.objects.create(report_type='paut_weld', document_filename='PPI-31-W5', **fields)
    Setup.objects.create(report=report, title='PAUT 1', manufacturer='Olympus', scope_platform='OmniScan X3',
                         scope_model='X3 32:128', transducer_model='10L32-A1', freq='10', wedge_angle='38.90',
                         beam_formation='Sectorial', foc_depth='0.420', gain='10.6', cal_block_serial='19019',
                         specimen_thickness='0.280', order=0)
    if rows:
        table = ResultsTable.objects.create(report=report, columns=get_report_type('paut_weld').results_headings)
        for i, cells in enumerate(rows):
            ResultsRow.objects.create(table=table, cells=cells, order=i)
    return report


class WeldBlockTests(TestCase):
    def test_scan_plans_block_fills_material_information(self):
        report = weld_report()
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        report.scan_plan = ScanPlan.objects.create(name='6in', thickness=0.28, index_offset=0.48, sensitivity_block=block)
        report.save()
        cells = weld_pages(report).report
        self.assertEqual((cells['U15'], cells['W14'], cells['W16'], cells['W17']),
                         ('6in Sch 40', '19019', 'Notch', 'Carbon Steel'))
        self.assertEqual((cells['Y20'], cells['Y21'], cells['Y26']), ('6.625"', 'Sch 40 / 0.280"', '37 degrees'))
        self.assertEqual((cells['C33'], cells['C34'], cells['L34']), ('480.5833 step/in.', '0.039"', '19019'))
        self.assertEqual((cells['L36'], cells['N36'], cells['P36']), ('0.280', '0.560', '0.840'))

    def test_side_drilled_hole_distances(self):
        self.assertEqual(excel_report._tcg_distances('0.1875'), {'L36': '0.188', 'N36': '0.562', 'P36': '1.125'})
        self.assertEqual(excel_report._tcg_distances(''), {})

    def test_without_a_block_the_setup_values_stay(self):
        cells = weld_pages(weld_report()).report
        self.assertEqual(cells['W14'], '19019')  # from the setup's cal block serial
        self.assertNotIn('U15', cells)


class WeldCellMapTests(TestCase):
    def test_header_and_people(self):
        report = weld_report(client='Flint Hills Resources', address='12555 Clark Rd', procedure='100-UT-20',
                             procedure_rev='9.0', work_order='WO5757163', report_date=datetime.date(2026, 10, 1),
                             notes='Both welds pass.')
        ReportPerson.objects.create(report=report, name='Tech One', certification='UT II', examined=True)
        ReportPerson.objects.create(report=report, name='Rev Two', certification='PAUT II', reviewed=True)
        cells = weld_pages(report).report
        self.assertEqual(cells['X2'], 'PPI-31-W5')
        self.assertEqual(cells['X3'], datetime.date(2026, 10, 1))
        self.assertEqual(cells['X5'], 'WO5757163')
        self.assertEqual((cells['C7'], cells['C8'], cells['U11'], cells['Z11']),
                         ('Flint Hills Resources', '12555 Clark Rd', '100-UT-20', '9.0'))
        self.assertEqual(cells['C53'], 'Both welds pass.')
        self.assertEqual((cells['C55'], cells['R55'], cells['C57'], cells['R57']),
                         ('Tech One', 'UT II', 'Rev Two', 'PAUT II'))

    def test_setups_fill_probe_and_group_columns_in_order(self):
        report = weld_report()
        Setup.objects.create(report=report, title='SW 1', transducer_model='C543', order=1)
        cells = weld_pages(report).report
        self.assertEqual(cells['A15'], 'OmniScan X3')
        self.assertEqual(cells['F15'], 'PAUT 1: 10L32-A1')
        self.assertEqual(cells['F18'], '10 MHz')
        self.assertEqual(cells['F24'], '38.90°')
        self.assertEqual(cells['G15'], 'SW 1: C543')
        self.assertEqual(cells['H15'], 'N/A')       # probe 3 unused
        self.assertEqual(cells['L16'], 'Sectorial')
        self.assertEqual(cells['L21'], 'N/A')       # sectorial: no VPA
        self.assertEqual(cells['L23'], '0.420"')
        self.assertEqual(cells['L30'], '10.6 dB')
        self.assertEqual(cells['N15'], 'SW 1: C543')
        self.assertEqual(cells['P15'], 'N/A')       # group 3 unused
        self.assertEqual(cells['W14'], '19019')
        self.assertEqual(cells['Y21'], '0.280"')

    def test_calibration_rows_only_for_entered_times(self):
        cells = weld_pages(weld_report(cal_time_initial='0700', cal_time_out='0900')).report
        self.assertEqual((cells['F34'], cells['G34'], cells['I34']), ('0700', 'Accept', 'Accept'))
        self.assertEqual((cells['F37'], cells['H37']), ('0900', 'Accept'))
        self.assertNotIn('F35', cells)
        self.assertNotIn('G35', cells)

    def test_results_rows_and_verdict_marks(self):
        report = weld_report([weld_row('W5', 'LOF', 'Accept'), weld_row('W6', '', 'Reject', 'Cut out')])
        cells = weld_pages(report).report
        self.assertEqual((cells['A41'], cells['C41'], cells['I41'], cells['Q41']), ('W5', 'RJA4201', '0.280', 'LOF'))
        self.assertEqual(cells['S41'], CHECK)
        self.assertNotIn('T41', cells)
        self.assertEqual(cells['T42'], CROSS)
        self.assertNotIn('S42', cells)
        self.assertEqual(cells['U42'], 'Cut out')

    def test_rows_past_page_one_go_to_the_continuation_page(self):
        rows = [weld_row(f'W{i}') for i in range(13)]
        pages = weld_pages(weld_report(rows, location='Pipe rack'))
        self.assertEqual(pages.report['A52'], 'W11')
        self.assertEqual(pages.continuation['A15'], 'W12')
        self.assertEqual(pages.continuation['C13'], 'Pipe rack')
        self.assertEqual(pages.page_count, 2)

    def test_no_continuation_page_when_results_fit(self):
        pages = weld_pages(weld_report([weld_row()]))
        self.assertEqual(pages.continuation, {})
        self.assertEqual(pages.page_count, 1)

    def test_one_indication_per_flaw_with_the_welds_images_in_order(self):
        report = weld_report([
            weld_row('W5', 'LOF', notes='Root LOF'),
            weld_row('', 'Slag', notes='Slag at cap'),   # second flaw on W5
            weld_row('W6', ''),                          # clean weld: no indication
        ])
        for i, name in enumerate(['first.png', 'second.png']):
            image = ReportImage(report=report, kind=ReportImage.SCAN, scan_id='W5', order=i)
            image.image.name = f'report_images/{name}'
            image.save()
        pages = weld_pages(report)
        self.assertEqual([(i.weld_id, i.number, i.notes) for i in pages.indications],
                         [('W5', 1, 'Root LOF'), ('W5', 2, 'Slag at cap')])
        self.assertTrue(pages.indications[0].image_path.endswith('first.png'))
        self.assertTrue(pages.indications[1].image_path.endswith('second.png'))
        self.assertEqual(pages.page_count, 3)


@mock.patch('reports.views.reports.excel_available', return_value=True)
@mock.patch('reports.views.reports.build_workbook', return_value=(FAKE_XLSX, FAKE_PDF))
class ExcelViewTests(TestCase):
    def test_download_is_an_xlsx_with_a_server_copy(self, build, _available):
        report = weld_report()
        with tempfile.TemporaryDirectory() as out, override_settings(REPORT_OUTPUT_DIR=out):
            resp = self.client.get(reverse('generate-report', args=[report.pk]))
            self.assertEqual(os.listdir(out), ['PPI-31-W5.xlsx'])
        self.assertIn('spreadsheetml', resp['Content-Type'])
        self.assertIn('PPI-31-W5.xlsx', resp['Content-Disposition'])
        self.assertEqual(b''.join(resp.streaming_content), FAKE_XLSX)
        self.assertEqual(build.call_args.kwargs.get('pdf', False), False)

    def test_pdf_is_made_by_excel(self, build, _available):
        report = weld_report()
        resp = self.client.get(reverse('report-pdf', args=[report.pk]))
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(resp.streaming_content), FAKE_PDF)
        self.assertTrue(build.call_args.kwargs['pdf'])

    def test_preview_and_editor_offer_xlsx(self, build, _available):
        report = weld_report()
        preview = self.client.get(reverse('preview-report', args=[report.pk]))
        self.assertContains(preview, 'Download .xlsx')
        self.assertContains(preview, 'Excel is building the PDF')
        self.assertNotContains(preview, 'docx-preview')
        editor = self.client.get(f"{reverse('create-report')}?loaded={report.pk}")
        self.assertContains(editor, 'Download .xlsx')

    def test_excel_error_returns_to_the_editor(self, build, _available):
        build.side_effect = excel_report.ExcelReportError('Excel could not create the report: boom')
        report = weld_report()
        resp = self.client.get(reverse('generate-report', args=[report.pk]))
        self.assertRedirects(resp, f"{reverse('create-report')}?loaded={report.pk}", fetch_redirect_response=False)
        self.assertIn('boom', [str(m) for m in get_messages(resp.wsgi_request)][0])


class ExcelMissingTests(TestCase):
    @mock.patch('reports.views.reports.excel_available', return_value=False)
    def test_preview_explains_excel_is_needed(self, _available):
        report = weld_report()
        resp = self.client.get(reverse('report-pdf', args=[report.pk]))
        self.assertEqual(resp.status_code, 503)
        self.assertContains(resp, 'need Microsoft Excel', status_code=503)
        self.assertContains(resp, 'saved as PDF from Excel', status_code=503)

    @override_settings(REPORT_PDF_ENGINE='off')
    def test_can_be_turned_off(self):
        self.assertFalse(excel_report.excel_available())


@unittest.skipUnless(os.environ.get('RUN_EXCEL_TESTS') == '1' and excel_report.excel_available(),
                     'set RUN_EXCEL_TESTS=1 on a PC with Excel to run the real Excel build')
class RealExcelTests(TestCase):
    def test_excel_makes_the_workbook_and_pdf(self):
        report = weld_report([weld_row('W5', 'LOF'), weld_row('W6')])
        report.scan_plan = ScanPlan.objects.create(name='6in', thickness=0.28, index_offset=0.48)
        report.save()
        xlsx, pdf = excel_report.build_workbook(report, pdf=True)
        self.assertTrue(xlsx.startswith(b'PK'))
        self.assertTrue(pdf.startswith(b'%PDF'))


class ScanPlanBoxTests(TestCase):
    def test_drawings_go_in_the_reference_sheets_boxes(self):
        from reports.services.excel_report import SCAN_PLAN_BOXES
        plan = ScanPlan(name='p', thickness=0.28, index_offset=0.48, skew_90=False, skew_270=True,
                        index_offset_2=0.75, skew_90_2=True, skew_270_2=False)
        boxes = [SCAN_PLAN_BOXES[(position, skew)] for position, _, skew in plan.drawings]
        self.assertEqual(boxes, ['E5:G19', 'B22:D36'])  # 270 deg top right, second offset 90 deg bottom left


class WeldFormEquipmentFieldTests(TestCase):
    def test_new_setup_fields_print_on_the_form(self):
        report = weld_report()
        setup = report.setups.get()
        for name, value in {'scope_cal_due': '1/16/2027', 'software_version': '5.20.0', 'scanner_type': 'SAUT',
                            'scanner_model': 'Jireh Microbe', 'cable_type': 'Integral', 'cable_length': "6'",
                            'wedge_material': 'Rex', 'wedge_curve': 'AOD', 'focal_plane': 'Depth',
                            'smoothing': 'Off', 'scanning_db': '+6dB', 'couplant': 'Glycerin',
                            'exam_surface': 'O.D.'}.items():
            setattr(setup, name, value)
        setup.save()
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        report.scan_plan = ScanPlan.objects.create(name='6in', thickness=0.28, index_offset=0.48, sensitivity_block=block)
        report.save()
        cells = weld_pages(report).report
        self.assertEqual((cells['C19'], cells['C23'], cells['C24']), ('1/16/2027', '5.20.0', 'SAUT'))
        self.assertEqual((cells['F19'], cells['F20'], cells['F22'], cells['F26']), ('Integral', "6'", 'Rex', 'AOD'))
        self.assertEqual((cells['L22'], cells['L27'], cells['L32']), ('Depth', 'Off', '+6dB'))
        # the setup's values win over the block's usual scanner and couplant
        self.assertEqual((cells['C25'], cells['W25'], cells['Y25'], cells['W24']),
                         ('Jireh Microbe', 'Glycerin', 'Glycerin', 'O.D.'))
        self.assertEqual(cells['C35'], '≤2in/s')  # no setup scan speed: the block's


class EquipmentGridTests(TestCase):
    """The reference job in the equipment grid: probe and group columns as on its Report sheet."""

    def setUp(self):
        from reports.models import ReportGroup, ReportProbe
        self.report = Report.objects.create(report_type='paut_weld', inst_name='Omniscan X3', inst_manufacturer='Olympus',
                                            inst_model='X3', inst_serial='QC-0030383', inst_software_version='5.20.0',
                                            inst_scan_speed='≤2in/s')
        new = lambda **kw: ReportProbe.objects.create(report=self.report, **kw)
        self.p1 = new(order=0, label='90°', kind='paut', make='Olympus', model='10L32-A1', frequency='10MHz',
                      cable_type='Integral', cable_length="6'", serial='Y2037', wedge_material='Rex',
                      wedge_model='SA1-N60S 10L32', wedge_angle='38.90 deg', probe_check='Accept')
        new(order=1, label='270°', kind='paut')
        self.p3 = new(order=2, label='0°', kind='conv_long', make='Olympus', model='D791', frequency='5MHz',
                      wedge_model='should not print')
        self.p4 = new(order=3, label='Trans', kind='conv_shear', make='Olympus', model='C543', wedge_model='ABS-4T',
                      wedge_angle='45deg')
        group = lambda **kw: ReportGroup.objects.create(report=self.report, **kw)
        group(order=0, probe=self.p1, scan='Sectorial', wave_mode='Shear', angles='42.0° - 73.0°', elements='1 - 27',
              angle_increment='1.0°', vpa='N/A', focal_plane='Depth', reference_db='10.6 dB', scanning_db='+6dB')
        group(order=1, probe=self.p1)
        group(order=2, probe=self.p1)
        group(order=3, label='0°', probe=self.p3, scan='Conventional', wave_mode='Longitudinal', elements='Dual',
              focal_plane='should not print')
        group(order=4, label='Trans', probe=self.p4, scan='Conventional', wave_mode='Shear', angles='45°')

    def test_instrument_probes_and_groups(self):
        cells = weld_pages(self.report).report
        self.assertEqual((cells['A15'], cells['C16'], cells['C18'], cells['C23'], cells['C35']),
                         ('Omniscan X3', 'Olympus', 'QC-0030383', '5.20.0', '≤2in/s'))
        self.assertEqual((cells['F13'], cells['F15'], cells['F17'], cells['F19'], cells['F23']),
                         ('Probe 1\n(90°)', 'PAUT 1: Olympus 10L32-A1', '10L32-A1', 'Integral', 'SA1-N60S 10L32'))
        self.assertEqual((cells['G13'], cells['G15']), ('Probe 2\n(270°)', 'PAUT 2'))
        self.assertEqual((cells['H15'], cells['H17'], cells['H23']), ('0deg 1: Olympus D791', 'D791', 'N/A'))
        self.assertEqual((cells['I15'], cells['I23'], cells['I24']), ('SW 1: Olympus C543', 'ABS-4T', '45deg'))
        # relevant groups: groups 1-3 use probe 1, group 4 probe 3, group 5 probe 4
        self.assertEqual((cells['F28'], cells['F29'], cells['F30']), ('1', '2', '3'))
        self.assertEqual((cells['H28'], cells['H29'], cells['I28']), ('4', 'N/A', '5'))
        self.assertEqual((cells['L13'], cells['L15'], cells['L16'], cells['L22'], cells['L32']),
                         ('Group 1', 'PAUT 1: Olympus 10L32-A1', 'Sectorial', 'Depth', '+6dB'))
        self.assertEqual((cells['Q13'], cells['Q15'], cells['Q19'], cells['Q22'], cells['Q20']),
                         ('Group 4 (0°)', '0deg 1: Olympus D791', 'Dual', 'N/A', 'N/A'))
        self.assertEqual((cells['S13'], cells['S17'], cells['S18']), ('Group 5 (Trans)', 'Shear', '45°'))

    def test_unused_columns_are_na(self):
        from reports.models import ReportGroup, ReportProbe
        ReportGroup.objects.filter(report=self.report, order__gte=1).delete()
        ReportProbe.objects.filter(report=self.report, order__gte=1).delete()
        cells = weld_pages(self.report).report
        self.assertEqual((cells['G15'], cells['I30'], cells['N15'], cells['S32']), ('N/A', 'N/A', 'N/A', 'N/A'))
