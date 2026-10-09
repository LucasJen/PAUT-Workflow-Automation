"""New weld report from files: reading a job's .nde files and building the report from them."""
import copy

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from reports.models import ReportDefaults
from reports.services.job_import import (
    build_report, calibration_window, guess_weld, place_columns, read_job_file, welds_from_files,
)
from reports.tests.test_nde_upload import FIXTURE, make_nde, sample_setup


def nde_file(name, offset_m=-0.0089, created='2026-09-28T08:09:57-04:00'):
    setup = sample_setup()
    for wedge in setup.get('wedges') or []:
        wedge.setdefault('positioning', {})['vCoordinateOffset'] = offset_m
    properties = copy.deepcopy(FIXTURE['properties'])
    properties.setdefault('file', {})['creationDate'] = created
    return SimpleUploadedFile(name, make_nde(setup, properties))


class NamesAndTimesTests(SimpleTestCase):
    def test_weld_from_the_file_name(self):
        self.assertEqual(guess_weld('PPI 31-37575 w5 n off1.nde'), 'W5')
        self.assertEqual(guess_weld('FHR 14-44929 W11 BOT.nde'), 'W11')
        self.assertEqual(guess_weld('Line FW-12 south.nde'), 'FW12')
        self.assertEqual(guess_weld('scan 3.nde'), '')

    def test_calibration_window(self):
        self.assertEqual(calibration_window(['2026-09-28 08:09', '2026-09-28 07:42', '']), ('0725', '0825'))
        self.assertEqual(calibration_window([]), ('', ''))

    def test_welds_and_their_sides(self):
        files = [{'filename': 'a', 'weld': 'W5', 'offset': 0.35, 'thickness': 0.28},
                 {'filename': 'b', 'weld': 'W5', 'offset': 0.35, 'thickness': 0.28},
                 {'filename': 'c', 'weld': 'W6', 'offset': 0.475, 'thickness': 0.28}]
        welds = welds_from_files(files)
        self.assertEqual(list(welds), ['W5', 'W6'])
        self.assertEqual((welds['W5']['location'], welds['W6']['location']), ('90/270', '90'))


class PlaceColumnsTests(SimpleTestCase):
    def item(self, kind='paut', model='10L32-A1', ref='a.nde#0', source='a.nde › GR-1', **group):
        return {'probe': {'kind': kind, 'model': model, 'source_file': ref.split('#')[0]}, 'probe_key': f'{model.lower()}|', 'probe_ref': ref,
                'group': {'scan': 'Sectorial', 'angles': '40-70', 'source_file': source, **group}}

    def test_defaults_columns_are_filled_by_kind(self):
        probes = [{'kind': 'paut', 'label': '90°', 'cable_type': 'Integral'}, {'kind': 'conv_long', 'label': '0°'}]
        groups = [{'probe_column': '0', 'smoothing': 'Off'}, {'probe_column': '1'}]
        probes, groups, skipped = place_columns(probes, groups, [self.item()])
        self.assertEqual(probes[0], {'kind': 'paut', 'label': '90°', 'cable_type': 'Integral', 'model': '10L32-A1',
                                     'source_file': 'a.nde'})
        self.assertEqual((groups[0]['scan'], groups[0]['smoothing'], groups[0]['probe_column']), ('Sectorial', 'Off', '0'))
        self.assertEqual((len(probes), len(groups), skipped), (2, 2, 0))

    def test_the_same_setup_on_another_weld_shares_its_group(self):
        items = [self.item(ref='w5.nde#0', source='w5.nde › GR-1'), self.item(ref='w6.nde#0', source='w6.nde › GR-1'),
                 self.item(ref='w7.nde#0', source='w7.nde › GR-1', angles='35-65')]
        probes, groups, _ = place_columns([], [], items)
        self.assertEqual(len(probes), 1)   # same model: one probe column
        self.assertEqual([g['angles'] for g in groups], ['40-70', '35-65'])

    def test_limits(self):
        items = [self.item(model=f'P{i}', ref=f'{i}', source=f'{i}', angles=str(i)) for i in range(6)]
        probes, groups, skipped = place_columns([], [], items)
        self.assertEqual((len(probes), skipped), (4, 2))


class BuildReportTests(TestCase):
    def test_a_report_from_a_jobs_files(self):
        files = [read_job_file(nde_file('PPI 31-37575 w5 n off1.nde')),
                 read_job_file(nde_file('PPI 31-37575 w5 s off1.nde', created='2026-09-28T08:30:00-04:00')),
                 read_job_file(SimpleUploadedFile('broken.nde', b'not hdf5'))]
        self.assertEqual([f.get('weld') for f in files[:2]], ['W5', 'W5'])
        self.assertIn('error', files[2])
        defaults = ReportDefaults.objects.create(
            report_type='paut_weld', name='Std', in_use=True, report_values={'client': 'PPI', 'procedure': '100-UT-20'},
            probe_columns=[{'kind': 'paut', 'cable_type': 'Integral'}], group_columns=[{'probe_column': '0', 'smoothing': 'Off'}])
        report, notes = build_report(files, defaults, 'PPI-31-37575-W5')
        self.assertEqual((report.report_type, report.document_filename, report.client), ('paut_weld', 'PPI-31-37575-W5', 'PPI'))
        self.assertEqual((report.cal_time_initial, report.cal_time_out), ('0750', '0845'))
        from datetime import date
        self.assertEqual(report.report_date, date.today())   # as a new report in the editor
        self.assertTrue(report.inst_serial)
        probe = report.probes.get()
        self.assertEqual((probe.cable_type, bool(probe.model)), ('Integral', True))
        group = report.groups.get()   # both files: the same setup, one group
        self.assertEqual((group.smoothing, group.probe, bool(group.scan)), ('Off', probe, True))
        rows = list(report.results_table.rows.values_list('cells', flat=True))
        self.assertEqual([(r[0], r[6]) for r in rows], [('W5', '90/270')])
        self.assertIsNotNone(report.scan_plan)


    def test_a_weld_scanned_at_two_offsets_has_both(self):
        files = [read_job_file(nde_file('PPI 31-37575 w5 n off1.nde')),
                 read_job_file(nde_file('PPI 31-37575 w5 n off2.nde'))]
        files[0]['offset'], files[1]['offset'] = 0.5, 0.875
        report, notes = build_report(files, None, 'Job')
        rows = list(report.results_table.rows.order_by('order').values_list('cells', flat=True))
        # a row per offset: the second with no Weld ID, the weld's location and thickness again
        self.assertEqual([(r[0], r[2], r[6], r[7]) for r in rows],
                         [('W5', '0.500', '90', rows[0][7]), ('', '0.875', '90', rows[0][7])])
        plan = report.scan_plan
        self.assertEqual((plan.index_offset, plan.index_offset_2), (0.5, 0.875))


class FromFilesPagesTests(TestCase):
    def test_upload_confirm_and_create(self):
        from django.urls import reverse
        defaults = ReportDefaults.objects.create(report_type='paut_weld', name='Std', in_use=True,
                                                 report_values={'client': 'PPI'})
        page = self.client.get(reverse('start-from-files'))
        self.assertContains(page, f'<option value="{defaults.pk}" selected>Std (in use)</option>')

        resp = self.client.post(reverse('start-from-files'), {
            'defaults': defaults.pk, 'units': 'imperial',
            'nde_files': [nde_file('PPI 31-37575 w5 n off1.nde'), nde_file('PPI 31-37575 w6 n off1.nde', offset_m=-0.012)]})
        self.assertRedirects(resp, reverse('confirm-job'))
        page = self.client.get(reverse('confirm-job'))
        self.assertContains(page, 'value="PPI-31-37575-W5&amp;W6"')
        self.assertContains(page, 'name="weld_1" value="W6"')

        from equipment.models import SensitivityBlock
        from reports.models import Report
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        resp = self.client.post(reverse('confirm-job'), {
            'document_filename': 'PPI-31-37575-W5&W6', 'sensitivity_block': block.pk, 'include_0': '1',
            'include_1': '1', 'weld_0': 'w5', 'weld_1': 'W6'})
        report = Report.objects.get()
        self.assertRedirects(resp, f"{reverse('create-report')}?loaded={report.pk}&wizard=1")
        self.assertEqual((report.client, report.document_filename), ('PPI', 'PPI-31-37575-W5&W6'))
        self.assertEqual([r[0] for r in report.results_table.rows.values_list('cells', flat=True)], ['W5', 'W6'])
        self.assertIsNone(self.client.session.get('job_import'))

    def test_the_picked_block_fills_the_report(self):
        from django.urls import reverse
        from equipment.models import SensitivityBlock
        from reports.models import Report
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 80')
        page = self.client.get(reverse('start-from-files'))
        self.assertContains(page, f'<option value="{block.pk}">6in Sch 80')
        self.client.post(reverse('start-from-files'), {
            'units': 'imperial', 'sensitivity_block': block.pk, 'nde_files': [nde_file('PPI 31-37575 w5 n off1.nde')]})
        page = self.client.get(reverse('confirm-job'))
        self.assertContains(page, f'<option value="{block.pk}" selected>')
        self.client.post(reverse('confirm-job'), {
            'document_filename': 'X', 'sensitivity_block': block.pk, 'include_0': '1', 'weld_0': 'W5'})
        report = Report.objects.get()
        self.assertEqual((report.sensitivity_block, report.pipe_size, report.cal_std_serial),
                         (block, '6in Sch 80', block.serial_number))

    def test_confirm_without_files_goes_back(self):
        from django.urls import reverse
        self.assertRedirects(self.client.get(reverse('confirm-job')), reverse('start-from-files'))


class GuidedEditorTests(TestCase):
    """The From-scan-files report opens in the guided editor: one step at a time, saved on each move."""

    def setUp(self):
        from django.urls import reverse
        self.report, _ = build_report([read_job_file(nde_file('PPI 31-37575 w5 n off1.nde'))], None, 'Job')
        self.editor = reverse('create-report')

    def post(self, goto, **fields):
        from reports.tests.test_create_report import post_data
        return self.client.post(self.editor, post_data(
            self.report, report_type='paut_weld', wizard='1', wizard_step='project', wizard_goto=goto, **fields))

    def test_the_guided_page(self):
        page = self.client.get(f'{self.editor}?loaded={self.report.pk}&wizard=1&step=materials')
        self.assertContains(page, 'data-wizard="1"')
        self.assertContains(page, 'name="wizard_step" id="wizard-step" value="materials"')
        self.assertContains(page, 'data-wizard-panel="scanplan"')
        self.assertContains(page, 'id="wizard-next"')
        self.assertNotContains(page, 'Save &amp; download')
        plain = self.client.get(f'{self.editor}?loaded={self.report.pk}')
        self.assertNotContains(plain, 'data-wizard')

    def test_the_scan_plan_step_shows_every_drawing(self):
        plan = self.report.scan_plan
        plan.index_offset, plan.skew_90, plan.skew_270 = 0.5, True, True
        plan.index_offset_2, plan.skew_90_2 = 1.25, True
        plan.save()
        page = self.client.get(f'{self.editor}?loaded={self.report.pk}&wizard=1&step=scanplan')
        for label, query in (('Offset 0.500" · 90° skew', 'position=1&amp;side=1'),
                             ('Offset 0.500" · 270° skew', 'position=1&amp;side=2'),
                             ('Offset 1.250" · 90° skew', 'position=2&amp;side=1')):
            self.assertContains(page, f'<figcaption>{label}'.replace('"', '&quot;'))
            self.assertContains(page, query)
        self.assertNotContains(page, 'position=2&amp;side=2')
        self.assertContains(page, '<span class="wizard-plan-welds">W5</span>', count=0)   # W5's offset is the file's
        self.assertContains(page, 'No weld in the results has this offset')

    def test_the_welds_at_each_offset(self):
        from reports.views.scan_plans import plan_drawing_views
        plan = self.report.scan_plan
        plan.index_offset, plan.skew_90, plan.skew_270 = 0.5, True, False
        plan.index_offset_2, plan.skew_90_2 = 0.875, True
        plan.save()
        row = self.report.results_table.rows.get()
        row.cells[2] = '0.500'
        row.save()
        offset_row = list(row.cells)
        offset_row[0], offset_row[2] = '', '0.875'
        row.table.rows.create(cells=offset_row, order=1)
        views = plan_drawing_views(self.report)
        self.assertEqual([(v['position'], v['side'], v['welds']) for v in views], [(1, 1, ['W5']), (2, 1, ['W5'])])

    def test_next_saves_and_goes_to_the_step(self):
        resp = self.post('equipment', client='Saved on Next')
        self.assertRedirects(resp, f'{self.editor}?loaded={self.report.pk}&wizard=1&step=equipment')
        self.report.refresh_from_db()
        self.assertEqual(self.report.client, 'Saved on Next')

    def test_the_last_step_is_the_preview(self):
        from django.urls import reverse
        resp = self.post('finish')
        preview = f"{reverse('preview-report', args=[self.report.pk])}?wizard=1"
        self.assertRedirects(resp, preview, fetch_redirect_response=False)
        page = self.client.get(preview)
        self.assertContains(page, f'{self.editor}?loaded={self.report.pk}&amp;wizard=1&amp;step=scanplan')
        self.assertContains(page, 'Open in full editor')

    def test_no_equipment_goes_back_to_its_step(self):
        self.report.probes.all().delete()
        self.report.groups.all().delete()
        resp = self.post('finish')
        self.assertRedirects(resp, f'{self.editor}?loaded={self.report.pk}&wizard=1&step=equipment')


class SetupBlockImportTests(TestCase):
    """The long form's Import .nde on a setup block."""

    def test_values_per_group_in_the_blocks_units(self):
        from django.urls import reverse
        data = self.client.post(reverse('nde-setup-values'), {'nde_file': nde_file('scan.nde'), 'units': 'metric'}).json()
        self.assertEqual(len(data['groups']), 1)
        values = data['groups'][0]['values']
        self.assertEqual((values['units'], values['source_file']), ('metric', 'scan.nde'))
        self.assertTrue(values['scope_model'])
        bad = self.client.post(reverse('nde-setup-values'), {'nde_file': SimpleUploadedFile('x.txt', b'x')})
        self.assertEqual(bad.status_code, 400)

    def test_each_setup_block_has_the_button(self):
        from django.urls import reverse
        page = self.client.get(reverse('create-report'))
        self.assertContains(page, 'class="btn btn-secondary btn-sm setup-nde-import" data-form-prefix="setups-0"')
        self.assertContains(page, 'id="setup-nde-file"')
