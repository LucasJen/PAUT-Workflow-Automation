import os
import tempfile
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from reports.models import Report, Setup
from reports.report_types import (
    DEFAULT_REPORT_TYPE, REPORT_SECTIONS, REPORT_TYPES, SECTIONS, ReportType, get_report_type,
)

REPORT_FIELDS = {f.name for f in Report._meta.concrete_fields}
SETUP_FIELDS = {f.name for f in Setup._meta.concrete_fields}


class RegistryTests(SimpleTestCase):
    """Guards against typos when a new report type is added."""

    def test_every_type_is_valid(self):
        for key, report_type in REPORT_TYPES.items():
            with self.subTest(type=key):
                self.assertEqual(report_type.key, key)
                path = os.path.join(settings.BASE_DIR, 'word_templates', report_type.template)
                self.assertTrue(os.path.exists(path), f'missing Word template {report_type.template}')
                self.assertLessEqual(set(report_type.sections), set(SECTIONS))
                self.assertLessEqual(set(report_type.hidden_fields), REPORT_FIELDS | SETUP_FIELDS)

    def test_sections_reference_real_fields(self):
        for key, _, names in REPORT_SECTIONS:
            for name in names or ():
                self.assertIn(name, REPORT_FIELDS, f'section {key} lists unknown field {name}')

    def test_unknown_key_falls_back_to_default(self):
        self.assertEqual(get_report_type('nope').key, DEFAULT_REPORT_TYPE)


class EditorTests(TestCase):
    url = reverse('create-report')

    def test_editor_renders_sections_and_type_config(self):
        resp = self.client.get(self.url)
        for key in SECTIONS:
            self.assertContains(resp, f'data-section="{key}"')
        self.assertContains(resp, 'id="report-types"')
        self.assertContains(resp, 'name="report_type"')

    def test_report_type_is_saved(self):
        self.client.post(self.url, {
            'report_id': '', 'report_type': DEFAULT_REPORT_TYPE,
            'setups-TOTAL_FORMS': '0', 'setups-INITIAL_FORMS': '0',
            'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0',
        })
        self.assertEqual(Report.objects.get().report_type, DEFAULT_REPORT_TYPE)

    def test_unknown_report_type_is_rejected(self):
        resp = self.client.post(self.url, {
            'report_id': '', 'report_type': 'made_up',
            'setups-TOTAL_FORMS': '0', 'setups-INITIAL_FORMS': '0',
            'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Report.objects.exists())

    def test_non_numeric_loaded_is_ignored(self):
        self.assertEqual(self.client.get(f'{self.url}?loaded=abc').status_code, 200)

    def test_saved_setups_offered_in_setup_blocks(self):
        Setup.objects.create(scope_model='OmniScan X3')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'OmniScan X3')
        self.assertContains(resp, 'id="saved-setup-values"')

    def test_old_urls_redirect_to_editor(self):
        report = Report.objects.create()
        self.assertRedirects(self.client.get(reverse('edit-report', args=[report.pk])),
                             f'{self.url}?loaded={report.pk}')
        self.assertRedirects(self.client.get(reverse('new-report')), self.url)
        self.assertEqual(Report.objects.count(), 1)  # no blank report created

    def test_delete_from_editor(self):
        report = Report.objects.create()
        resp = self.client.post(reverse('report-list'), {'selected': [report.pk], 'delete': ''}, follow=True)
        self.assertContains(resp, 'Deleted 1 report.')
        self.assertFalse(Report.objects.exists())


class GenerateUsesTypeTemplateTests(TestCase):
    def test_generate_uses_the_report_types_template(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        report = Report.objects.create(document_filename='typed', report_type='other')
        Setup.objects.create(report=report)
        other = ReportType('other', 'Other', 'long_form_template.docx')

        with override_settings(REPORT_OUTPUT_DIR=tmp.name), \
                mock.patch('reports.views.reports.get_report_type', return_value=other) as lookup, \
                mock.patch('reports.views.reports.WordTemplateProcessor') as processor:
            resp = self.client.get(reverse('generate-report', args=[report.pk]), follow=True)

        lookup.assert_called_once_with('other')
        template_path = processor.call_args.args[0]
        self.assertTrue(template_path.endswith(os.path.join('word_templates', 'long_form_template.docx')))
        self.assertContains(resp, 'Report generated: outputs/typed.docx')
