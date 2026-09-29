"""PDF preview/download made by Word. Word itself is mocked, except in the optional real test."""
import os
import tempfile
import unittest
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from reports.models import Report, Setup
from reports.services import word_pdf
from reports.services.report_render import render_report

FAKE_PDF = b'%PDF-1.7 fake'


def report_with_setup():
    report = Report.objects.create(document_filename='15V3 report')
    Setup.objects.create(report=report, title='HydroFORM')
    return report


@mock.patch('reports.views.reports.word_available', return_value=True)
@mock.patch('reports.views.reports.docx_to_pdf', return_value=FAKE_PDF)
class PdfViewTests(TestCase):
    def test_inline_pdf_for_preview(self, convert, _available):
        report = report_with_setup()
        with tempfile.TemporaryDirectory() as out, override_settings(REPORT_OUTPUT_DIR=out):
            resp = self.client.get(reverse('report-pdf', args=[report.pk]))
            self.assertEqual(os.listdir(out), [])  # previews don't write a server copy
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertNotIn('attachment', resp.get('Content-Disposition', ''))
        self.assertEqual(b''.join(resp.streaming_content), FAKE_PDF)
        # Word updates fields itself, so the docx it gets must not ask to update on open
        self.assertNotIn(b'w:updateFields', _settings_xml(convert.call_args.args[0]))

    def test_pdf_may_be_framed_only_by_the_app_itself(self, convert, _available):
        """The preview page shows the PDF in an iframe; Django's default X-Frame-Options DENY blocked it."""
        report = report_with_setup()
        self.assertEqual(self.client.get(reverse('report-pdf', args=[report.pk]))['X-Frame-Options'], 'SAMEORIGIN')
        convert.side_effect = word_pdf.WordPdfError('boom')  # the error page is shown in the same frame
        self.assertEqual(self.client.get(reverse('report-pdf', args=[report.pk]))['X-Frame-Options'], 'SAMEORIGIN')
        # Everything else keeps the stricter default
        self.assertEqual(self.client.get(reverse('preview-report', args=[report.pk]))['X-Frame-Options'], 'DENY')

    def test_download_pdf_saves_server_copy(self, convert, _available):
        report = report_with_setup()
        with tempfile.TemporaryDirectory() as out, override_settings(REPORT_OUTPUT_DIR=out):
            resp = self.client.get(reverse('report-pdf', args=[report.pk]) + '?download=1')
            self.assertEqual(os.listdir(out), ['15V3 report.pdf'])
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertIn('15V3 report.pdf', resp['Content-Disposition'])

    def test_word_failure_inline_shows_message(self, convert, _available):
        convert.side_effect = word_pdf.WordPdfError('Word could not create the PDF: boom')
        resp = self.client.get(reverse('report-pdf', args=[report_with_setup().pk]))
        self.assertEqual(resp.status_code, 503)
        self.assertContains(resp, 'boom', status_code=503)

    def test_word_failure_on_download_returns_to_editor(self, convert, _available):
        convert.side_effect = word_pdf.WordPdfError('Word could not create the PDF: boom')
        report = report_with_setup()
        resp = self.client.get(reverse('report-pdf', args=[report.pk]) + '?download=1', follow=True)
        self.assertContains(resp, 'boom')

    def test_preview_page_uses_word_pdf(self, convert, _available):
        report = report_with_setup()
        with mock.patch('reports.views.reports.word_available', return_value=True):
            resp = self.client.get(reverse('preview-report', args=[report.pk]))
        self.assertContains(resp, f'data-pdf-url="{reverse("report-pdf", args=[report.pk])}"')
        self.assertNotContains(resp, 'docx-preview.min.js')
        self.assertContains(resp, 'Download PDF')

    def test_buttons_shown_in_editor_and_list(self, convert, _available):
        report = report_with_setup()
        pdf_url = reverse('report-pdf', args=[report.pk]) + '?download=1'
        self.assertContains(self.client.get(f"{reverse('create-report')}?loaded={report.pk}"), pdf_url)
        self.assertContains(self.client.get(reverse('report-list')), pdf_url)


@mock.patch('reports.views.reports.word_available', return_value=False)
class NoWordTests(TestCase):
    def test_preview_falls_back_to_in_browser_docx(self, _available):
        report = report_with_setup()
        resp = self.client.get(reverse('preview-report', args=[report.pk]))
        self.assertContains(resp, 'docx-preview.min.js')
        self.assertContains(resp, f'data-docx-url="{reverse("report-docx", args=[report.pk])}"')
        self.assertNotContains(resp, 'Download PDF')

    def test_pdf_endpoint_explains(self, _available):
        resp = self.client.get(reverse('report-pdf', args=[report_with_setup().pk]))
        self.assertContains(resp, 'needs Microsoft Word', status_code=503)

    def test_no_pdf_buttons(self, _available):
        report = report_with_setup()
        self.assertNotContains(self.client.get(reverse('report-list')), reverse('report-pdf', args=[report.pk]))


class WordAvailableTests(TestCase):
    @override_settings(REPORT_PDF_ENGINE='off')
    def test_can_be_turned_off(self):
        self.assertFalse(word_pdf.word_available())


def _settings_xml(docx_bytes):
    import io
    import zipfile
    return zipfile.ZipFile(io.BytesIO(docx_bytes)).read('word/settings.xml')


@unittest.skipUnless(os.environ.get('RUN_WORD_TESTS') == '1' and word_pdf.word_available(),
                     'set RUN_WORD_TESTS=1 on a PC with Word to run the real Word conversion')
class RealWordConversionTests(TestCase):
    def test_word_makes_a_pdf(self):
        pdf = word_pdf.docx_to_pdf(render_report(report_with_setup(), update_fields_on_open=False))
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertGreater(len(pdf), 10_000)
