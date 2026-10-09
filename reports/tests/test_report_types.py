import os
import tempfile
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from reports.models import Report, ReportImage, Setup
from reports.report_types import (
    DEFAULT_REPORT_TYPE, EDITOR_PARTS, REPORT_SECTIONS, REPORT_TYPES, SECTIONS, ReportType, get_report_type,
)

REPORT_FIELDS = {f.name for f in Report._meta.concrete_fields}
SETUP_FIELDS = {f.name for f in Setup._meta.concrete_fields}
IMAGE_FIELDS = {f.name for f in ReportImage._meta.get_fields()}


class RegistryTests(SimpleTestCase):
    """Guards against typos when a new report type is added."""

    def test_every_type_is_valid(self):
        for key, report_type in REPORT_TYPES.items():
            with self.subTest(type=key):
                self.assertEqual(report_type.key, key)
                folder = {'docx': 'word_templates', 'xlsx': 'excel_templates'}[report_type.output_format]
                path = os.path.join(settings.BASE_DIR, folder, report_type.template)
                self.assertTrue(os.path.exists(path), f'missing template {folder}/{report_type.template}')
                self.assertLessEqual(set(report_type.sections), set(SECTIONS))
                names = {name.removeprefix('setup.') for name in report_type.hidden_fields}
                self.assertLessEqual(names, REPORT_FIELDS | SETUP_FIELDS | IMAGE_FIELDS | EDITOR_PARTS)
                for name in report_type.hidden_fields:
                    if name.startswith('setup.'):
                        self.assertIn(name.removeprefix('setup.'), SETUP_FIELDS)

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
            'drawings-TOTAL_FORMS': '0', 'drawings-INITIAL_FORMS': '0',
            'people-TOTAL_FORMS': '0', 'people-INITIAL_FORMS': '0',
        })
        self.assertEqual(Report.objects.get().report_type, DEFAULT_REPORT_TYPE)

    def test_unknown_report_type_is_rejected(self):
        resp = self.client.post(self.url, {
            'report_id': '', 'report_type': 'made_up',
            'setups-TOTAL_FORMS': '0', 'setups-INITIAL_FORMS': '0',
            'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0',
            'drawings-TOTAL_FORMS': '0', 'drawings-INITIAL_FORMS': '0',
            'people-TOTAL_FORMS': '0', 'people-INITIAL_FORMS': '0',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Report.objects.exists())

    def test_non_numeric_loaded_is_ignored(self):
        self.assertEqual(self.client.get(f'{self.url}?loaded=abc').status_code, 200)

    def test_saved_setups_offered_in_setup_blocks(self):
        Setup.objects.create(scope_model='OmniScan X3')
        resp = self.client.get(self.url)
        self.assertContains(resp, 'OmniScan X3')
        # Its values are fetched when picked, not carried by the page
        self.assertNotContains(resp, 'id="saved-setup-values"')
        self.assertContains(resp, 'data-saved-setup-url="/setup/0/values.json"')

    def test_saved_setup_values_are_fetched_when_picked(self):
        setup = Setup.objects.create(scope_model='OmniScan X3', report=Report.objects.create())
        data = self.client.get(reverse('saved-setup-json', args=[setup.pk])).json()
        self.assertEqual(data['values']['scope_model'], 'OmniScan X3')
        self.assertNotIn('report', data['values'])
        self.assertIn('probe', data['columns'])
        self.assertEqual(self.client.get(reverse('saved-setup-json', args=[setup.pk + 99])).status_code, 404)

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
        other = ReportType('other', 'Other', 'other_template.docx')

        with override_settings(REPORT_OUTPUT_DIR=tmp.name), \
                mock.patch('reports.services.report_render.get_report_type', return_value=other) as lookup, \
                mock.patch('reports.services.report_render.DocxTemplate') as template:
            resp = self.client.get(reverse('generate-report', args=[report.pk]))

        self.assertTrue(lookup.call_args_list)
        self.assertTrue(all(c.args == ('other',) for c in lookup.call_args_list))
        self.assertTrue(template.call_args.args[0].endswith(os.path.join('word_templates', 'other_template.docx')))
        self.assertEqual(resp.status_code, 200)


class WeldEditorTests(TestCase):
    def test_weld_report_hides_results_photos_and_screenshots(self):
        weld = get_report_type('paut_weld')
        self.assertNotIn('results', weld.sections)
        self.assertNotIn('images', weld.sections)
        self.assertIn('cal_images', weld.hidden_fields)
        hic = get_report_type('paut_long')
        self.assertIn('results', hic.sections)
        self.assertNotIn('cal_images', hic.hidden_fields)
        report = Report.objects.create(report_type='paut_weld')
        Setup.objects.create(report=report)
        page = self.client.get(f"{reverse('create-report')}?loaded={report.pk}")
        self.assertContains(page, 'data-field="cal_images"')
