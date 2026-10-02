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
        self.assertEqual(self.client.get(reverse('new-defaults', args=['nope'])).status_code, 404)

    def test_saves_only_filled_fields_and_no_per_job_fields(self):
        page = self.client.get(reverse('new-defaults', args=['paut_long'])).content.decode()
        self.assertIn('name="setup-cable_type"', page)       # a setup field
        self.assertNotIn('name="document_filename"', page)   # per job
        self.assertNotIn('name="setup-source_file"', page)   # from the .nde
        self.assertNotIn('name="probe-kind"', page)          # the weld grid only

    def test_weld_defaults_page_is_the_report_grid(self):
        page = self.client.get(reverse('new-defaults', args=['paut_weld'])).content.decode()
        self.assertIn('name="procedure_rev"', page)          # a weld form field
        self.assertIn('id="probe-grid"', page)
        self.assertIn('id="probes-column-template"', page)
        self.assertIn('name="inst_name"', page)              # testing instrument, in the grid
        self.assertNotIn('name="setup-cable_type"', page)    # the weld form has no setup blocks
        self.assertNotIn('id="weld-grid-toolbar"', page)     # no imports on a defaults set

    def test_weld_defaults_save_prefilled_columns(self):
        data = {
            'defaults_name': 'Standard', 'procedure': '100-UT-20', 'inst_name': 'OmniScan X3',
            'probes-TOTAL_FORMS': '3', 'probes-INITIAL_FORMS': '0',
            'probes-0-kind': 'paut', 'probes-0-label': '90°', 'probes-0-cable_type': 'Integral',
            'probes-1-kind': 'paut', 'probes-1-model': 'gone', 'probes-1-DELETE': 'on',
            'probes-2-kind': 'conv_long', 'probes-2-label': '0°', 'probes-2-probe_check': 'Accept',
            'groups-TOTAL_FORMS': '3', 'groups-INITIAL_FORMS': '0',
            'groups-0-probe_column': '0', 'groups-0-scan': 'Sectorial', 'groups-0-smoothing': 'On',
            'groups-1-probe_column': '2', 'groups-1-label': '0°', 'groups-1-scan': 'Conventional',
            'groups-2-probe_column': '', 'groups-2-kind': '',
        }
        self.client.post(reverse('new-defaults', args=['paut_weld']), data)
        record = ReportDefaults.objects.get()
        self.assertEqual(record.report_values, {'procedure': '100-UT-20', 'cal_accept': False, 'inst_name': 'OmniScan X3'})
        self.assertEqual(record.probe_columns, [
            {'kind': 'paut', 'label': '90°', 'cable_type': 'Integral'},
            {'kind': 'conv_long', 'label': '0°', 'probe_check': 'Accept'},
        ])
        self.assertEqual(record.group_columns, [
            {'scan': 'Sectorial', 'smoothing': 'On', 'probe_column': '0'},
            {'label': '0°', 'scan': 'Conventional', 'probe_column': '1'},
        ])

        # Shown again as columns, with the groups on their probes
        resp = self.client.get(reverse('edit-defaults', args=[record.pk]))
        self.assertContains(resp, 'value="Integral"')
        self.assertEqual([f['probe_column'].value() for f in resp.context['group_formset'].forms], ['0', '1'])

        # ...and offered to new reports of the type
        defaults = self.client.get(reverse('create-report')).context['report_defaults']['paut_weld']
        self.assertEqual((len(defaults['probes']), len(defaults['groups'])), (2, 2))

    def test_weld_defaults_keep_the_page_order(self):
        self.client.post(reverse('new-defaults', args=['paut_weld']), {
            'defaults_name': 'Standard',
            'probes-TOTAL_FORMS': '2', 'probes-INITIAL_FORMS': '0',
            'probes-0-kind': 'paut', 'probes-0-label': 'first', 'probes-0-ORDER': '2',
            'probes-1-kind': 'conv_long', 'probes-1-label': 'second', 'probes-1-ORDER': '1',
            'groups-TOTAL_FORMS': '2', 'groups-INITIAL_FORMS': '0',
            'groups-0-probe_column': '0', 'groups-0-label': 'on first', 'groups-0-ORDER': '2',
            'groups-1-probe_column': '1', 'groups-1-label': 'on second', 'groups-1-ORDER': '1',
        })
        record = ReportDefaults.objects.get()
        self.assertEqual([p['label'] for p in record.probe_columns], ['second', 'first'])
        self.assertEqual(record.group_columns, [{'label': 'on second', 'probe_column': '0'},
                                                {'label': 'on first', 'probe_column': '1'}])

    def test_weld_defaults_can_accept_calibration(self):
        self.assertContains(self.client.get(reverse('new-defaults', args=['paut_weld'])), 'name="cal_accept"')
        self.client.post(reverse('new-defaults', args=['paut_weld']), {'defaults_name': 'Standard', 'cal_accept': 'on'})
        self.assertIs(ReportDefaults.objects.get().report_values['cal_accept'], True)

    def test_weld_defaults_keep_na_groups(self):
        self.client.post(reverse('new-defaults', args=['paut_weld']), {
            'defaults_name': 'Standard',
            'probes-TOTAL_FORMS': '0', 'probes-INITIAL_FORMS': '0',
            'groups-TOTAL_FORMS': '1', 'groups-INITIAL_FORMS': '0', 'groups-0-probe_column': 'na', 'groups-0-label': 'x',
        })
        self.assertEqual(ReportDefaults.objects.get().group_columns, [{'label': 'x', 'probe_column': 'na'}])

    def test_weld_save_keeps_setup_values_and_unposted_columns(self):
        record = ReportDefaults.objects.create(report_type='paut_weld', name='Old', setup_values={'couplant': 'Water'},
                                               probe_columns=[{'kind': 'paut', 'label': 'P'}])
        self.client.post(reverse('edit-defaults', args=[record.pk]), {'defaults_name': 'Old'})
        record.refresh_from_db()
        self.assertEqual(record.setup_values, {'couplant': 'Water'})
        self.assertEqual(record.probe_columns, [{'kind': 'paut', 'label': 'P'}])


class NewReportTests(TestCase):
    def setUp(self):
        ReportDefaults.objects.create(report_type=DEFAULT_REPORT_TYPE,
                                      in_use=True,
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


class DefaultSetsTests(TestCase):
    def test_several_sets_one_in_use(self):
        first = self.client.post(reverse('new-defaults', args=['paut_weld']),
                                 {'defaults_name': 'Standard', 'procedure': '100-UT-20'})
        standard = ReportDefaults.objects.get(name='Standard')
        self.assertTrue(standard.in_use)  # the first set of a type is used straight away
        self.assertRedirects(first, reverse('edit-defaults', args=[standard.pk]))
        self.client.post(reverse('new-defaults', args=['paut_weld']),
                         {'defaults_name': 'PPI Pine Bend', 'procedure': '100-UT-31'})
        ppi = ReportDefaults.objects.get(name='PPI Pine Bend')
        self.assertFalse(ppi.in_use)
        self.assertEqual(defaults_for('paut_weld')[0]['procedure'], '100-UT-20')

        self.client.post(reverse('defaults-list'), {'pk': ppi.pk, 'use': ''})
        self.assertEqual(defaults_for('paut_weld')[0]['procedure'], '100-UT-31')
        self.assertEqual(ReportDefaults.objects.filter(report_type='paut_weld', in_use=True).count(), 1)

        # ticking 'Used for new reports' on the edit page switches too
        self.client.post(reverse('edit-defaults', args=[standard.pk]),
                         {'defaults_name': 'Standard', 'procedure': '100-UT-20', 'in_use': '1'})
        self.assertEqual(defaults_for('paut_weld')[0]['procedure'], '100-UT-20')
        self.assertEqual(defaults_for('paut_long'), ({}, {}))  # other types unaffected

    def test_names_are_unique_per_type(self):
        ReportDefaults.objects.create(report_type='paut_weld', name='Standard')
        resp = self.client.post(reverse('new-defaults', args=['paut_weld']), {'defaults_name': 'Standard'})
        self.assertContains(resp, 'There is already a PAUT weld (Excel) defaults set called')
        ReportDefaults.objects.create(report_type='paut_long', name='Standard')  # fine for another type

    def test_duplicate_and_delete(self):
        item = ReportDefaults.objects.create(report_type='paut_weld', name='Standard', in_use=True,
                                             report_values={'procedure': 'X'})
        self.client.post(reverse('defaults-list'), {'pk': item.pk, 'duplicate': ''})
        copy = ReportDefaults.objects.get(name='Standard (copy)')
        self.assertEqual((copy.report_values, copy.in_use), ({'procedure': 'X'}, False))
        self.client.post(reverse('defaults-list'), {'pk': copy.pk, 'delete': ''})
        self.assertFalse(ReportDefaults.objects.filter(name='Standard (copy)').exists())
        page = self.client.get(reverse('defaults-list'))
        self.assertContains(page, 'In use')
