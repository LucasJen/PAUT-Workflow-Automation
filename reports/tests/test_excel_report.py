"""Excel weld report: the cell map, the views, and (optionally) a real Excel run."""
import datetime
import os
import tempfile
import unittest
from unittest import mock

from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from reports.models import Report, ReportImage, ReportPerson, ResultsRow, ResultsTable, Setup
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
        xlsx, pdf = excel_report.build_workbook(report, pdf=True)
        self.assertTrue(xlsx.startswith(b'PK'))
        self.assertTrue(pdf.startswith(b'%PDF'))
