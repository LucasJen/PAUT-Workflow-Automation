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
