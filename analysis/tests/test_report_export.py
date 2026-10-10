import base64
import datetime
import json
import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from analysis.models import Indication
from analysis.services import report_export
from reports.models import Report, ReportImage, ResultsTable
from reports.report_types import CORROSION_THICKNESS_COLUMNS, WELD_RESULTS_COLUMNS

IN = 0.0254
# A 1 x 1 PNG
PNG = 'data:image/png;base64,' + base64.b64encode(
    bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                  '1f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082')).decode()


def weld_indication(**extra):
    values = dict(file_path=r'C:\jobs\45-19662\fw6 n off1.nde', file_name='fw6 n off1.nde', group=0, number=1,
                  scan=329, lateral=21, scan_position=12.953 * IN, index_position=-0.5 * IN, angle=64.0,
                  readings={'A%': 44.0, 'DA^': 0.291 * IN, 'ViA^': 0.141 * IN, 'Length': 0.307 * IN, 'Peak%': 51.2},
                  cursors={'s_ref': 12.80 * IN, 's_meas': 13.107 * IN, 'u_ref': 0.25 * IN, 'u_meas': 0.31 * IN},
                  comment='Root indication')
    values.update(extra)
    return Indication.objects.create(**values)


def raster_indication(**extra):
    values = dict(file_path=r'C:\jobs\31e33a\wh 12x12.nde', file_name='wh 12x12.nde', group=0, number=1,
                  scan=118, lateral=29, scan_position=4.629 * IN, index_position=1.153 * IN, angle=None,
                  readings={'A%': 223.2, 'A/-I/': 0.402 * IN, 'TminZ': 0.383 * IN, 'TavgZ': 0.395 * IN},
                  cursors={'s_ref': 4.0 * IN, 's_meas': 4.303 * IN, 'i_ref': 0.5 * IN, 'i_meas': 1.731 * IN},
                  comment='Mid-wall lamination')
    values.update(extra)
    return Indication.objects.create(**values)


class MappingTests(TestCase):
    def test_columns_fill_by_the_report_types_keys_then_by_heading_words(self):
        weld = WELD_RESULTS_COLUMNS
        self.assertEqual(report_export.field_for('Length (in)', weld), 'length')
        self.assertEqual(report_export.field_for('% Amp', weld), 'amplitude')
        self.assertEqual(report_export.field_for('Axial Pos. (in)', weld), 'index_pos')
        self.assertIsNone(report_export.field_for('Weld ID', weld))           # the weld's own, left for the user
        self.assertIsNone(report_export.field_for('Accept / Reject', weld))
        corrosion = CORROSION_THICKNESS_COLUMNS
        self.assertEqual(report_export.field_for('Min. Thickness (in.)', corrosion), 'thickness_min')
        self.assertEqual(report_export.field_for('Results', corrosion), 'comment')
        # A Long Form's own columns
        self.assertEqual(report_export.field_for('Flaw Length (mm)', ()), 'length')
        self.assertEqual(report_export.field_for('Through-wall', ()), 'height')
        self.assertEqual(report_export.units_for('Flaw Length (mm)', 'in'), 'mm')
        self.assertEqual(report_export.units_for('Min. Thk (in.)', 'mm'), 'in')
        self.assertEqual(report_export.units_for('Comments', 'mm'), 'mm')

    def test_weld_row_and_its_picture_on_the_indication_key(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        report = Report.objects.create(report_type='paut_weld', document_filename='PPI weld')
        headings = [h for _, h in WELD_RESULTS_COLUMNS]
        table = ResultsTable.objects.create(report=report, columns=headings)
        table.rows.create(cells=['FW6'] + [''] * (len(headings) - 1), order=0)
        before = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        Report.objects.filter(pk=report.pk).update(updated_at=before)
        ind = weld_indication()
        out = report_export.preview(report, [ind], 'in')
        row = dict(zip(out['columns'], out['rows'][0]))
        self.assertEqual(row['Length (in)'], '0.307')
        self.assertEqual(row['Depth (in)'], '0.291')
        self.assertEqual(row['Height (in)'], '0.060')
        self.assertEqual(row['% Amp'], '51.2')                 # the sized peak over the cursor's A%
        self.assertEqual(row['Circ Start (in)'], '12.800')
        self.assertEqual(row['Axial Pos. (in)'], '0.141')
        self.assertEqual(row['Notes / Comments'], 'Root indication')
        self.assertEqual(row['Weld ID'], '')                   # under the weld above it on the form
        with override_settings(MEDIA_ROOT=folder):
            added = report_export.append(report, out['columns'], out['rows'], [PNG], ['x'])
        self.assertEqual(added, 1)
        rows = list(table.rows.order_by('order'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].cells[0], 'FW6')              # the report's own rows stay first
        key = rows[1].cells[len(headings)]
        self.assertRegex(key, r'^ind-[0-9a-f]{12}$')
        image = ReportImage.objects.get(report=report)
        self.assertEqual((image.kind, image.scan_id), (ReportImage.INDICATION, key))
        self.assertGreater(Report.objects.get(pk=report.pk).updated_at, before)

    def test_corrosion_row_ranges_thickness_and_scan_picture(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        report = Report.objects.create(report_type='paut_corrosion', document_filename='Short form')
        a, b = raster_indication(), raster_indication(number=2, comment='')
        out = report_export.preview(report, [a, b], 'in')   # no table yet: the type's columns
        self.assertEqual(out['columns'], [h for _, h in CORROSION_THICKNESS_COLUMNS])
        row = dict(zip(out['columns'], out['rows'][0]))
        self.assertEqual(row['Scan ID'], 'wh 12x12 #1')         # two from one file: numbered
        self.assertEqual(row['Axial Start / Stop'], '0.500 - 1.731')
        self.assertEqual(row['Circ Start / Stop'], '4.000 - 4.303')
        self.assertEqual(row['Min. Thickness (in.)'], '0.383')
        self.assertEqual(row['Avg. Thickness (in.)'], '0.395')
        with override_settings(MEDIA_ROOT=folder):
            report_export.append(report, out['columns'], out['rows'], [PNG, None], ['a', 'b'])
        self.assertEqual(report.results_table.rows.count(), 2)
        self.assertEqual(len(report.results_table.rows.first().cells), len(out['columns']))   # no key cell
        image = ReportImage.objects.get(report=report)
        self.assertEqual((image.kind, image.scan_id), (ReportImage.SCAN, 'wh 12x12 #1'))

    def test_long_form_columns_follow_their_own_units_and_renamed_ones_fill_by_words(self):
        report = Report.objects.create(report_type='paut_long')
        out = report_export.preview(report, [raster_indication()], 'mm')
        row = dict(zip(out['columns'], out['rows'][0]))
        self.assertEqual(row['Scan ID'], 'wh 12x12')              # one from the file: its name
        self.assertEqual(row['X Axis (Circ.) Start/Stop (In.)'], '4.000 - 4.303')   # the heading says inches
        self.assertEqual(row['Min. Thk (in.)'], '0.383')
        self.assertEqual(row['Scan Orient.'], '')
        # A table whose user changed its columns
        ResultsTable.objects.create(report=report, columns=['Location', 'Flaw Length (mm)', 'Remarks'])
        out = report_export.preview(report, [weld_indication()], 'in')
        self.assertEqual(out['rows'][0], ['', '7.8', 'Root indication'])
        report_export.append(report, out['columns'], out['rows'])
        self.assertEqual(report.results_table.rows.count(), 1)

    def test_an_issued_report_or_changed_columns_are_refused(self):
        report = Report.objects.create(report_type='paut_long', status=Report.ISSUED)
        with self.assertRaises(report_export.ExportError):
            report_export.append(report, ['A'], [['1']])
        report = Report.objects.create(report_type='paut_long')
        ResultsTable.objects.create(report=report, columns=['A', 'B'])
        with self.assertRaises(report_export.ExportError):
            report_export.append(report, ['A'], [['1']])


class SendApiTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def post(self, name, body):
        return self.client.post(reverse(name), json.dumps(body), content_type='application/json')

    def test_reports_from_this_job_folder_come_first(self):
        other = Report.objects.create(report_type='paut_long', document_filename='Newest, elsewhere')
        mine = Report.objects.create(report_type='paut_weld', document_filename='This job', job_folder=r'C:\jobs\45-19662')
        Report.objects.filter(pk=other.pk).update(updated_at=Report.objects.get(pk=mine.pk).updated_at)
        Report.objects.create(report_type='paut_weld', status=Report.ISSUED, document_filename='Issued')
        data = self.client.get(reverse('analysis-report-targets'), {'path': r'C:\jobs\45-19662\fw6 n off1.nde'}).json()
        names = [r['name'] for r in data['reports']]
        self.assertEqual(names[0], 'This job')
        self.assertTrue(data['reports'][0]['this_job'])
        self.assertNotIn('Issued', names)

    def test_preview_then_send(self):
        report = Report.objects.create(report_type='paut_weld', document_filename='PPI weld')
        ind = weld_indication()
        preview = self.post('analysis-report-preview', {'report': report.pk, 'indications': [ind.pk], 'units': 'in'}).json()
        self.assertEqual(preview['report']['name'], 'PPI weld')
        rows = preview['rows']
        rows[0][preview['columns'].index('Type')] = 'LOF'     # edited in the preview
        with override_settings(MEDIA_ROOT=self.folder):
            response = self.post('analysis-report-send', {'report': report.pk, 'indications': [ind.pk],
                                                          'columns': preview['columns'], 'rows': rows, 'pictures': [PNG]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['edit_url'], reverse('edit-report', args=[report.pk]))
        cells = report.results_table.rows.get().cells
        self.assertEqual(cells[preview['columns'].index('Type')], 'LOF')
        self.assertEqual(ReportImage.objects.filter(report=report).count(), 1)

    def test_errors_are_explained(self):
        report = Report.objects.create(report_type='paut_long', status=Report.ISSUED)
        ind = weld_indication()
        self.assertEqual(self.post('analysis-report-preview', {'report': 999, 'indications': [ind.pk]}).status_code, 400)
        self.assertEqual(self.post('analysis-report-preview', {'report': report.pk, 'indications': []}).status_code, 400)
        response = self.post('analysis-report-send', {'report': report.pk, 'indications': [ind.pk],
                                                      'columns': ['A'], 'rows': [['1']]})
        self.assertEqual(response.status_code, 409)
        self.assertIn('issued', response.json()['error'])
