import os
import tempfile

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from docx import Document

from reports.models import Report, Setup
from reports.views.reports import safe_filename


class SafeFilenameTests(SimpleTestCase):
    def test_strips_directories(self):
        for name in ['../../evil', '..\\..\\evil', 'C:\\Windows\\evil', '/etc/evil']:
            result = safe_filename(name)
            self.assertNotIn('/', result)
            self.assertNotIn('\\', result)
            self.assertNotIn(':', result)
            self.assertFalse(result.startswith('.'))

    def test_keeps_normal_names(self):
        self.assertEqual(safe_filename('Unit 3 - Weld 12'), 'Unit 3 - Weld 12')

    def test_blank_and_reserved_names_fall_back(self):
        for name in ['', '   ', '...', 'CON', 'nul']:
            self.assertEqual(safe_filename(name), 'report')


class GenerateReportOutputTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(REPORT_OUTPUT_DIR=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

    def generate(self, report):
        return self.client.get(reverse('generate-report', args=[report.pk]))

    def test_output_stays_in_output_dir(self):
        report = Report.objects.create(document_filename='../escape')
        Setup.objects.create(report=report)
        self.generate(report)
        self.assertEqual(os.listdir(self.tmp.name), ['_escape.docx'])

    def test_placeholders_are_filled(self):
        report = Report.objects.create(document_filename='fill', client='ACME Refining')
        Setup.objects.create(report=report, scope_model='OmniScan X3')
        self.generate(report)

        doc = Document(os.path.join(self.tmp.name, 'fill.docx'))
        text = '\n'.join(
            [p.text for p in doc.paragraphs]
            + [c.text for t in doc.tables for r in t.rows for c in r.cells]
        )
        self.assertIn('ACME Refining', text)
        self.assertIn('OmniScan X3', text)
        self.assertNotIn('{{CLIENT}}', text)
        self.assertNotIn('{{SCOPE_MODEL}}', text)
