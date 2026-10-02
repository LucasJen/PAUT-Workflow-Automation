from django.test import TestCase
from django.urls import reverse

from reports.models import Report, ReportGroup, ReportProbe
from reports.tests.test_create_report import management, post_data


def grid_data(probes=(), groups=(), initial_probes=0, initial_groups=0):
    """The weld form grid's POST fields: lists of dicts of column fields (may include 'id', 'DELETE')."""
    data = {}
    data.update(management('probes', len(probes), initial_probes))
    data.update(management('groups', len(groups), initial_groups))
    for prefix, columns in (('probes', probes), ('groups', groups)):
        for i, column in enumerate(columns):
            for k, v in column.items():
                data[f'{prefix}-{i}-{k}'] = v
    return data


class WeldGridTests(TestCase):
    url = reverse('create-report')

    def post(self, report=None, **grid):
        data = post_data(report=report, report_type='paut_weld')
        data.update(grid_data(**grid))
        return self.client.post(self.url, data)

    def test_new_columns_save_in_order_and_groups_use_their_probe_column(self):
        resp = self.post(
            probes=[{'kind': 'paut', 'label': '90°', 'model': '10L32-A1'},
                    {'kind': 'conv_long', 'label': '0°', 'model': 'D791'}],
            groups=[{'label': 'G1', 'probe_column': '0', 'scan': 'Sectorial'},
                    {'label': '0°', 'probe_column': '1', 'scan': 'Linear'},
                    {'label': 'Loose', 'probe_column': ''}],
        )
        report = Report.objects.get()
        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')
        self.assertEqual(list(report.probes.values_list('model', 'order', 'kind')),
                         [('10L32-A1', 0, 'paut'), ('D791', 1, 'conv_long')])
        self.assertEqual(
            [(g.label, g.order, g.probe.model if g.probe else None) for g in report.groups.all()],
            [('G1', 0, '10L32-A1'), ('0°', 1, 'D791'), ('Loose', 2, None)])

    def test_columns_save_in_their_page_order(self):
        report = Report.objects.create(report_type='paut_weld')
        a = ReportProbe.objects.create(report=report, order=0, model='A')
        b = ReportProbe.objects.create(report=report, order=1, model='B')
        g = ReportGroup.objects.create(report=report, order=0, label='G', probe=a)
        # B moved in front of A, a new probe C in between; the group still points at A (form 0)
        self.post(
            report,
            probes=[{'id': a.pk, 'kind': 'paut', 'model': 'A', 'ORDER': '3'},
                    {'id': b.pk, 'kind': 'paut', 'model': 'B', 'ORDER': '1'},
                    {'kind': 'paut', 'model': 'C', 'ORDER': '2'}],
            groups=[{'id': g.pk, 'label': 'G', 'probe_column': '0', 'ORDER': '1'},
                    {'kind': '', 'ORDER': '2'}],
            initial_probes=2, initial_groups=1,
        )
        self.assertEqual(list(report.probes.values_list('model', 'order')), [('B', 0), ('C', 1), ('A', 2)])
        g.refresh_from_db()
        self.assertEqual(g.probe, a)
        self.assertEqual(report.groups.count(), 1)   # an untouched new column with only its place is skipped

    def test_na_group_is_saved_and_shown_again(self):
        self.post(probes=[{'kind': 'na', 'label': '270°'}],
                  groups=[{'label': 'spare', 'probe_column': 'na'}])
        report = Report.objects.get()
        group = report.groups.get()
        self.assertEqual((group.not_applicable, group.probe, report.probes.get().kind), (True, None, 'na'))
        resp = self.client.get(f'{self.url}?loaded={report.pk}')
        self.assertEqual(resp.context['group_formset'].forms[0]['probe_column'].value(), 'na')

    def test_untouched_new_column_is_skipped(self):
        self.post(probes=[{'kind': 'paut', 'model': 'A'}, {'kind': 'paut'}])
        self.assertEqual(list(ReportProbe.objects.values_list('model', flat=True)), ['A'])

    def test_removed_columns_are_deleted_and_the_rest_renumbered(self):
        report = Report.objects.create(report_type='paut_weld')
        p0 = ReportProbe.objects.create(report=report, order=0, model='Drop')
        p1 = ReportProbe.objects.create(report=report, order=1, model='Keep')
        g0 = ReportGroup.objects.create(report=report, order=0, label='G', probe=p1)

        self.post(
            report,
            probes=[{'id': p0.pk, 'kind': 'paut', 'model': 'Drop', 'DELETE': 'on'},
                    {'id': p1.pk, 'kind': 'paut', 'model': 'Keep'},
                    {'kind': 'paut', 'model': 'New', 'DELETE': 'on'}],
            groups=[{'id': g0.pk, 'label': 'G', 'probe_column': '1'}],
            initial_probes=2, initial_groups=1,
        )

        self.assertEqual(list(report.probes.values_list('model', 'order')), [('Keep', 0)])
        g0.refresh_from_db()
        self.assertEqual(g0.probe, p1)

    def test_loaded_report_shows_columns_with_their_probe_choice(self):
        report = Report.objects.create(report_type='paut_weld')
        ReportProbe.objects.create(report=report, order=0, model='First')
        p1 = ReportProbe.objects.create(report=report, order=1, model='Second')
        ReportGroup.objects.create(report=report, order=0, label='G', probe=p1)

        html = self.client.get(f'{self.url}?loaded={report.pk}').content.decode()

        self.assertIn('id="probe-grid"', html)
        self.assertIn('name="probes-1-model"', html)
        self.assertIn('value="Second"', html)
        self.assertRegex(html, r'<option value="1" selected>P2</option>')
        self.assertIn('id="probes-column-template"', html)

    def test_report_with_only_columns_can_be_downloaded(self):
        report = Report.objects.create(report_type='paut_weld')
        ReportProbe.objects.create(report=report, order=0, model='P')
        html = self.client.get(f'{self.url}?loaded={report.pk}').content.decode()
        self.assertIn('id="download-link"', html)

    def test_editor_without_grid_post_leaves_columns_alone(self):
        report = Report.objects.create(report_type='paut_weld')
        ReportProbe.objects.create(report=report, order=0, model='P')
        self.client.post(self.url, post_data(report=report, report_type='paut_weld'))
        self.assertEqual(report.probes.count(), 1)


class WeldColumnsTests(TestCase):
    def test_setup_values_map_to_columns_with_units(self):
        from reports.weld_columns import columns_from_setup
        columns = columns_from_setup({
            'units': 'imperial', 'beam_formation': 'Sectorial', 'wave_propagation': 'Shear',
            'manufacturer': 'Evident', 'transducer_model': '10L32-A1', 'transducer_serial': 'Q1', 'freq': '10',
            'wedge_angle': '36', 'foc_depth': '1.5', 'gain': '12.4', 'catalogue_probe': 7, 'scope_model': 'X3',
            'x_res': '0.04', 'element_aperture': '16', 'element_step': '1', 'cable_type': None,
        })
        self.assertEqual(columns['probe']['kind'], 'paut')
        self.assertEqual((columns['probe']['frequency'], columns['probe']['wedge_angle'], columns['probe']['catalogue_probe']),
                         ('10 MHz', '36°', '7'))
        self.assertNotIn('cable_type', columns['probe'])
        self.assertEqual((columns['group']['focal_distance'], columns['group']['reference_db'], columns['group']['vpa']),
                         ('1.5"', '12.4 dB', 'N/A'))
        self.assertEqual((columns['instrument']['inst_name'], columns['instrument']['inst_scan_res']), ('X3', '0.04"'))
        self.assertEqual(columns['probe_key'], '10l32-a1|q1')

    def test_conventional_kinds(self):
        from reports.weld_columns import kind
        self.assertEqual(kind({'beam_formation': 'Conventional', 'wave_propagation': 'Longitudinal'}), 'conv_long')
        self.assertEqual(kind({'beam_formation': 'Conventional', 'wave_propagation': 'Shear'}), 'conv_shear')

    def test_editor_offers_saved_setups_as_columns(self):
        from reports.models import Setup
        setup = Setup.objects.create(transducer_model='D791', beam_formation='Conventional', wave_propagation='Longitudinal')
        resp = self.client.get(reverse('create-report'))
        self.assertEqual(resp.context['saved_setup_columns'][setup.pk]['probe']['kind'], 'conv_long')
        self.assertContains(resp, 'id="weld-setup-loader"')


class NdeColumnsTests(TestCase):
    url = reverse('nde-columns')

    def test_each_inspection_group_is_a_probe_and_group(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from reports.tests.test_nde_upload import FIXTURE, make_nde, sample_setup
        resp = self.client.post(self.url, {
            'nde_file': SimpleUploadedFile('scan.nde', make_nde(sample_setup(), FIXTURE['properties'])), 'units': 'metric'})
        data = resp.json()
        self.assertEqual(len(data['columns']), 1)
        column = data['columns'][0]
        self.assertEqual(column['instrument']['inst_model'], 'OmniScan X3 64 - 64:128PR')
        self.assertTrue(column['probe']['model'])
        self.assertTrue(column['probe_key'])
        self.assertNotIn(' · ', column['label'])
        self.assertEqual((column['probe']['source_file'], column['group']['source_file']), ('scan.nde', 'scan.nde'))

    def test_not_an_nde_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.client.post(self.url, {'nde_file': SimpleUploadedFile('scan.txt', b'x')})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())


class ScanPlanFromGroupTests(TestCase):
    def test_scan_plan_can_fill_from_a_weld_report_group(self):
        report = Report.objects.create(report_type='paut_weld', document_filename='W5')
        probe = ReportProbe.objects.create(report=report, order=0, model='10L32-A1', wedge_angle='36°',
                                           wedge_primary_offset=-20.0, wedge_first_element_height=8.0)
        group = ReportGroup.objects.create(report=report, order=0, label='90°', probe=probe, angles='40.0° - 70.0°',
                                           angle_increment='1.0°', first_element=1, aperture_elements=16)
        resp = self.client.get(reverse('new-scan-plan'))
        item = resp.context['group_fill_values'][f'g{group.pk}']
        self.assertEqual(item['fields'], {'angle_start': 40.0, 'angle_stop': 70.0, 'angle_step': 1.0,
                                          'first_element': 1, 'aperture_elements': 16})
        self.assertEqual((item['wedge_geometry']['wedge_primary_offset'], item['wedge_geometry']['wedge_angle']), (-20.0, 36.0))
        self.assertIn('W5 · Group 1 (90°) · 10L32-A1', item['label'])
        self.assertContains(resp, 'Weld report groups')


class WeldPersonnelTests(TestCase):
    def test_weld_report_has_two_signature_lines_not_a_people_list(self):
        from reports.report_types import get_report_type
        self.assertIn('weld_personnel', get_report_type('paut_weld').sections)
        self.assertNotIn('personnel', get_report_type('paut_weld').sections)
        self.assertIn('personnel', get_report_type('paut_long').sections)
        self.assertNotIn('weld_personnel', get_report_type('paut_long').sections)

    def test_lines_save_and_known_names_are_offered(self):
        data = post_data(report_type='paut_weld', weld_technician='Lucas Jennings', weld_technician_cert='UT II',
                         weld_reviewer='Sky Tervo')
        self.client.post(reverse('create-report'), data)
        report = Report.objects.get()
        self.assertEqual((report.weld_technician, report.weld_technician_cert, report.weld_reviewer),
                         ('Lucas Jennings', 'UT II', 'Sky Tervo'))
        page = self.client.get(reverse('create-report'))
        self.assertIn(('Lucas Jennings', 'UT II'), page.context['known_people'])
        self.assertContains(page, 'data-cert-field="weld_technician_cert"')

    def test_weld_defaults_include_the_lines(self):
        self.assertContains(self.client.get(reverse('new-defaults', args=['paut_weld'])), 'name="weld_reviewer"')
