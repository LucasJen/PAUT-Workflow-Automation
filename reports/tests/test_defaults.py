"""Library › Defaults: per report type starting values for new reports and setups."""
from django.test import TestCase
from django.urls import reverse

from reports.defaults import defaults_for
from reports.models import Report, ReportDefaults, Setup
from reports.report_types import DEFAULT_REPORT_TYPE

EMPTY_FORMSETS = {
    'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0',
    'drawings-TOTAL_FORMS': '0', 'drawings-INITIAL_FORMS': '0',
    'people-TOTAL_FORMS': '0', 'people-INITIAL_FORMS': '0',
}


class DefaultsPageTests(TestCase):
    def test_library_tabs_and_pages(self):
        self.assertContains(self.client.get(reverse('snippet-list')), 'href="%s"' % reverse('defaults-list'))
        page = self.client.get(reverse('defaults-list'))
        self.assertContains(page, 'PAUT weld (Excel)')
        self.assertContains(page, 'PAUT long form (HIC)')
        self.assertEqual(self.client.get(reverse('edit-defaults', args=['nope'])).status_code, 404)

    def test_saves_only_filled_fields_and_no_per_job_fields(self):
        page = self.client.get(reverse('edit-defaults', args=['paut_weld'])).content.decode()
        self.assertIn('name="procedure_rev"', page)          # a weld form field
        self.assertIn('name="setup-cable_type"', page)       # a setup field
        self.assertNotIn('name="document_filename"', page)   # per job
        self.assertNotIn('name="setup-source_file"', page)   # from the .nde
        self.client.post(reverse('edit-defaults', args=['paut_weld']), {
            'procedure': '100-UT-20', 'procedure_rev': '9.0', 'setup-cable_type': 'Integral',
            'setup-cable_length': "6'", 'setup-units': 'imperial',
        })
        report_values, setup_values = defaults_for('paut_weld')
        self.assertEqual(report_values, {'procedure': '100-UT-20', 'procedure_rev': '9.0'})
        self.assertEqual((setup_values['cable_type'], setup_values['cable_length']), ('Integral', "6'"))
        self.assertNotIn('report_type', report_values)


class NewReportTests(TestCase):
    def setUp(self):
        ReportDefaults.objects.create(report_type=DEFAULT_REPORT_TYPE,
                                      report_values={'procedure': '100-UT-31', 'client': 'Flint Hills Resources'},
                                      setup_values={'couplant': 'Water', 'cable_type': 'Integral'})

    def test_new_report_opens_with_the_defaults(self):
        page = self.client.get(reverse('create-report'))
        form = page.context['form']
        self.assertEqual((form['procedure'].value(), form['client'].value()), ('100-UT-31', 'Flint Hills Resources'))
        setup_form = page.context['setup_formset'].forms[0]
        self.assertEqual((setup_form['couplant'].value(), setup_form['cable_type'].value()), ('Water', 'Integral'))
        self.assertContains(page, 'id="report-defaults"')

    def test_loaded_report_keeps_its_own_values(self):
        report = Report.objects.create(procedure='OTHER')
        form = self.client.get(f"{reverse('create-report')}?loaded={report.pk}").context['form']
        self.assertEqual(form['procedure'].value(), 'OTHER')

    def post(self, setup):
        prefix = {f'setups-0-{k}': v for k, v in setup.items()}
        return self.client.post(reverse('create-report'), {
            'report_id': '', 'report_type': DEFAULT_REPORT_TYPE, 'procedure': '100-UT-31',
            'setups-TOTAL_FORMS': '1', 'setups-INITIAL_FORMS': '0', **prefix, **EMPTY_FORMSETS,
        })

    def test_a_setup_block_with_only_defaults_is_not_saved(self):
        self.post({'couplant': 'Water', 'cable_type': 'Integral', 'manufacturer': 'Evident', 'units': 'imperial'})
        self.assertTrue(Report.objects.exists())
        self.assertFalse(Setup.objects.exists())

    def test_a_filled_in_setup_is_saved_with_its_defaults(self):
        self.post({'couplant': 'Water', 'cable_type': 'Integral', 'manufacturer': 'Evident', 'units': 'imperial',
                   'title': 'PAUT 1'})
        setup = Setup.objects.get()
        self.assertEqual((setup.title, setup.couplant, setup.cable_type), ('PAUT 1', 'Water', 'Integral'))
