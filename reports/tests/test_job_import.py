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
        self.assertTrue(report.inst_serial)
        probe = report.probes.get()
        self.assertEqual((probe.cable_type, bool(probe.model)), ('Integral', True))
        group = report.groups.get()   # both files: the same setup, one group
        self.assertEqual((group.smoothing, group.probe, bool(group.scan)), ('Off', probe, True))
        rows = list(report.results_table.rows.values_list('cells', flat=True))
        self.assertEqual([(r[0], r[6]) for r in rows], [('W5', '90/270')])
        self.assertIsNotNone(report.scan_plan)
