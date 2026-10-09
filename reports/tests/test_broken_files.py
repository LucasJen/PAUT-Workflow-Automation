"""A missing or broken file is a message (or a left-out picture), not a server error."""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from reports.models import Report, ReportImage, Setup, SetupImage
from reports.services.excel_report import ExcelReportError, build_workbook
from reports.services.report_render import render_report
from reports.tests.test_phase2 import MediaMixin, png


class BrokenFileTests(MediaMixin, TestCase):
    def test_a_broken_picture_is_left_out_of_the_word_report(self):
        report = Report.objects.create()
        setup = Setup.objects.create(report=report, title='HydroFORM')
        SetupImage.objects.create(setup=setup, image=SimpleUploadedFile('cal.png', b'not a picture'))
        ReportImage.objects.create(report=report, kind=ReportImage.DRAWING, image=png('ok.png'))
        self.assertTrue(render_report(report))   # renders, without the broken one

    def test_a_word_report_that_cant_be_made_is_a_message(self):
        report = Report.objects.create()
        Setup.objects.create(report=report)
        with mock.patch('reports.views.reports.render_report', side_effect=ValueError('template broken')):
            resp = self.client.get(reverse('generate-report', args=[report.pk]), HTTP_X_DOWNLOAD='1')
            self.assertEqual(resp.status_code, 409)
            self.assertIn('template broken', resp.json()['error'])
            resp = self.client.get(reverse('report-docx', args=[report.pk]))
            self.assertEqual(resp.status_code, 500)
            self.assertContains(resp, 'template broken', status_code=500)

    def test_an_excel_report_that_cant_be_prepared_is_an_excel_error(self):
        report = Report.objects.create(report_type='paut_weld')
        with mock.patch('reports.services.excel_report.template_path', return_value='C:/nowhere/missing.xlsx'):
            with self.assertRaisesMessage(ExcelReportError, 'The report could not be prepared'):
                build_workbook(report)


class OutputWarningTests(MediaMixin, TestCase):
    """What the Excel forms leave out is said in the editor and on the download."""

    def test_weld_columns_and_results_beyond_the_form(self):
        from reports.models import ReportGroup, ReportProbe, ResultsRow, ResultsTable
        from reports.report_types import WELD_RESULTS_COLUMNS
        from reports.services.excel_report import output_warnings
        report = Report.objects.create(report_type='paut_weld')
        for i in range(5):
            ReportProbe.objects.create(report=report, order=i)
        table = ResultsTable.objects.create(report=report, columns=[h for _, h in WELD_RESULTS_COLUMNS])
        for i in range(47):
            ResultsRow.objects.create(table=table, cells=[f'W{i}'], order=i)
        self.assertEqual(output_warnings(report), [
            'The results need 93 rows (with a blank row between welds); the form holds 45, so the last 24 are left out.',
            'The report has 5 probe columns; the form holds 4, so the last one is left out.'])
        page = self.client.get(f"{reverse('create-report')}?loaded={report.pk}")
        self.assertContains(page, 'the form holds 45')
        ReportGroup.objects.create(report=report)
        with mock.patch('reports.views.reports.excel_available', return_value=True), \
                mock.patch('reports.views.reports.build_workbook', return_value=(b'xlsx', None)), \
                mock.patch('reports.views.reports._save_copy'):
            resp = self.client.get(reverse('generate-report', args=[report.pk]), HTTP_X_DOWNLOAD='1')
        self.assertIn('the form holds 45', resp['X-Report-Warnings'])

    def test_short_form_setup_images_after_the_first(self):
        from reports.services.excel_report import output_warnings
        report = Report.objects.create(report_type='paut_corrosion')
        setup = Setup.objects.create(report=report)
        SetupImage.objects.create(setup=setup, image=png('a.png'), order=0)
        self.assertEqual(output_warnings(report), [])
        SetupImage.objects.create(setup=setup, image=png('b.png'), order=1)
        self.assertEqual(output_warnings(report),
                         ['Setup 1 has 2 setup images; only the first prints on its Setup Information page.'])
