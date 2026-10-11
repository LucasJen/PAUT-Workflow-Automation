"""Guided Creation from an existing weld report: the .xlsx reader and the weld form read back into a report."""
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from reports.models import Report, ReportImage
from reports.results import report_results
from reports.services.excel_report import results_layout, weld_pages
from reports.services.weld_report_import import WeldReportError, import_weld_report, read_weld_report
from reports.services.xlsx_reader import format_number, read_workbook

THREE_DECIMALS = 1   # style index of the 0.000 number format in make_xlsx
A_DATE = 2           # style index of a date


def _cell(ref, value):
    if isinstance(value, date):
        serial = (value - date(1899, 12, 30)).days
        return f'<c r="{ref}" s="{A_DATE}"><v>{serial}</v></c>'
    if isinstance(value, float):
        return f'<c r="{ref}" s="{THREE_DECIMALS}"><v>{value}</v></c>'
    if isinstance(value, int):
        return f'<c r="{ref}"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def make_xlsx(sheets, pictures=None):
    """
    A workbook: {sheet name: {ref: value}} (str inline, float in a 0.000 cell, int plain, date),
    with {sheet name: [(png bytes, from col, from row, to col, to row)]} pictures (0-based anchors).
    """
    pictures = pictures or {}
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        sheet_nodes, rels = [], []
        for i, name in enumerate(sheets, start=1):
            sheet_nodes.append(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
            rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
            rows = {}
            for ref, value in sheets[name].items():
                row = int(''.join(ch for ch in ref if ch.isdigit()))
                rows.setdefault(row, []).append(_cell(ref, value))
            data = ''.join(f'<row r="{r}">{"".join(cells)}</row>' for r, cells in sorted(rows.items()))
            drawing = ''
            if name in pictures:
                drawing = '<drawing r:id="rIdD"/>'
                z.writestr(f'xl/worksheets/_rels/sheet{i}.xml.rels',
                           '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           f'<Relationship Id="rIdD" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing{i}.xml"/></Relationships>')
                anchors, image_rels = [], []
                for k, (png, c1, r1, c2, r2) in enumerate(pictures[name], start=1):
                    z.writestr(f'xl/media/image{i}_{k}.png', png)
                    image_rels.append(f'<Relationship Id="rIdI{k}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image{i}_{k}.png"/>')
                    anchors.append(
                        f'<xdr:twoCellAnchor><xdr:from><xdr:col>{c1}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
                        f'<xdr:to><xdr:col>{c2}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r2}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
                        f'<xdr:pic><xdr:blipFill><a:blip r:embed="rIdI{k}"/></xdr:blipFill></xdr:pic><xdr:clientData/></xdr:twoCellAnchor>')
                z.writestr(f'xl/drawings/drawing{i}.xml',
                           '<?xml version="1.0"?><xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
                           'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                           + ''.join(anchors) + '</xdr:wsDr>')
                z.writestr(f'xl/drawings/_rels/drawing{i}.xml.rels',
                           '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                           + ''.join(image_rels) + '</Relationships>')
            z.writestr(f'xl/worksheets/sheet{i}.xml',
                       '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                       f'<sheetData>{data}</sheetData>{drawing}</worksheet>')
        z.writestr('xl/workbook.xml',
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets>{"".join(sheet_nodes)}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + ''.join(rels) + '</Relationships>')
        z.writestr('xl/styles.xml',
                   '<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.000"/></numFmts>'
                   '<cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="14"/></cellXfs></styleSheet>')
    out.seek(0)
    return out


def png(colour='red', size=(40, 20)):
    buffer = io.BytesIO()
    Image.new('RGB', size, colour).save(buffer, 'PNG')
    return buffer.getvalue()


FORM_LABELS = {'A7': 'Customer', 'E16': 'Make', 'J16': 'Scan', 'U16': 'Block Type', 'E34': 'Initial',
               'A40': 'Weld ID', 'A53': 'Notes:', 'A55': 'Technician:'}


def weld_form_sheets():
    """The reference job's weld form (PPI-31-37575-W5&W6): Report page, a Continuation page, an Indication page."""
    report = dict(FORM_LABELS)
    report.update({
        'X2': 'PPI-31-37575-W5&W6-6inch', 'X3': date(2026, 9, 28), 'X5': 'WO5757163', 'C7': 'Flint Hills Resources',
        'C8': '12555 Clark Rd', 'C9': 'PPI @ Pine Bend', 'C10': '(2) 6-inch butt welds', 'C11': 'ASME Section V, Art. 4',
        'L11': 'B31.3', 'U11': '100-UT-20', 'Z11': '9.0', 'C39': 'West of Cooling Tower 5',
        'C53': 'Both welds pass per B31.3.', 'C55': 'Lucas Jennings', 'R55': 'UT II', 'C57': 'Sky Tervo', 'R57': 'UT II',
        # Testing instrument
        'A15': 'Omniscan X3', 'C16': 'Olympus', 'C17': 'X3', 'C18': 'QC-0030383', 'C23': '5.20.0', 'C35': '≤2in/s',
        # Probes: PAUT on F, N/A (270°) on G, 0° on H, transverse SW on I
        'F13': 'Probe 1\n(90°)', 'G13': 'Probe 2\n(270°)', 'H13': 'Probe 3 \n(0°)', 'I13': 'Probe 4\n(Trans)',
        'F15': 'PAUT 1: Olympus 10L32-A1', 'F16': 'Olympus', 'F17': '10L32-A1', 'F18': '10MHz', 'F21': 'Y2037',
        'F23': 'SA1-N60S 10L32', 'F24': '38.90 deg', 'F27': 'Accept', 'F28': 1,
        **{f'G{r}': 'N/A' for r in range(15, 31)},
        'H15': '0deg 1: Olympus D791', 'H17': 'D791', 'H23': 'N/A', 'H21': 1345425,
        'I15': 'SW 1: Olympus C543', 'I17': 'C543', 'I23': 'ABS-4T',
        # Groups: L on probe 1, N and P unused, Q on the 0°, S on the SW probe
        'Q13': 'Group 4       (0°)',
        'L15': 'PAUT 1: Olympus 10L32-A1', 'L16': 'Sectorial', 'L18': '42.0° - 73.0°', 'L30': '10.6 dB',
        **{f'{c}{r}': 'N/A' for c in 'NP' for r in range(15, 33)},
        'Q15': '0deg 1: Olympus D791', 'Q16': 'Conventional', 'Q20': 'N/A', 'S15': 'SW 1: Olympus C543', 'S18': '45°',
        # Material information and TCG
        'U15': '6in Sch 40', 'W14': 19019, 'W17': 'Carbon Steel', 'Y21': 'Sch 40 / 0.280"', 'W28': '10 Step',
        'L34': 19019, 'Q34': 19019, 'L35': 'Notch', 'L36': 0.28, 'L37': '80%',
        # Calibration
        'F34': '0700', 'F35': 'Accept', 'F37': '0900',
        # Results: W5 with an indication at two offsets, W6 with none (blank rows between)
        'A41': 'W5', 'C41': 'RJA4201', 'D41': 0.475, 'E41': 0.8, 'H41': '90/270', 'I41': 0.28, 'K41': 7.905, 'L41': 0.212,
        'Q41': 'LOF', 'S41': 'P', 'U41': 'Passes per B31.3',
        'D42': 0.875, 'I42': 0.28, 'K42': 10.0, 'Q42': 'Slag', 'T42': '☓', 'U42': 'Cut out',
        'A44': 'W6', 'C44': 'RCK6859', 'D44': 0.475, 'S44': 'P', 'U44': 'No rejectable indications',
        # the template's check marks in an empty row
        'S52': 'P', 'T52': '☓',
    })
    continuation = {'A14': 'Weld ID', 'A48': 'Notes:', 'A15': 'W7', 'D15': 0.5, 'K15': 1.25, 'Q15': 'Porosity',
                    'S15': 'P', 'S16': 'P', 'T16': '☓'}
    indication = {'A12': 'Insert Picture of Indication', 'A57': 'Weld Number', 'C57': 'W5', 'L57': '2'}
    return {'Report': report, 'Continuation sheet': continuation, 'Indication ##': indication}


class XlsxReaderTests(unittest.TestCase):
    def test_number_formats(self):
        self.assertEqual(format_number(0.28, '0.000'), '0.280')
        self.assertEqual(format_number(8.0, '0%'), '800%')
        self.assertEqual(format_number(700.0, '0000'), '0700')
        self.assertEqual(format_number(0.5, '0.000\\"'), '0.500"')
        self.assertEqual(format_number(0.5, '0.000 "in"'), '0.500 in')
        self.assertEqual(format_number(1.5, '0.0##'), '1.5')
        self.assertEqual(format_number(75.1, 'General'), '75.1')
        self.assertEqual(format_number(1345425.0, 'General'), '1345425')

    def test_cells_dates_and_pictures(self):
        sheets = read_workbook(make_xlsx({'One': {'A1': 'text', 'B2': 0.28, 'C3': 7, 'D4': date(2026, 9, 28)},
                                          'Two': {}}, {'Two': [(png(), 0, 11, 5, 20)]}))
        self.assertEqual(list(sheets), ['One', 'Two'])
        one = sheets['One']
        self.assertEqual((one.text('A1'), one.text('B2'), one.text('C3'), one.text('D4')), ('text', '0.280', '7', '09/28/2026'))
        self.assertEqual(sheets['Two'].pictures[0].row, 12)
        self.assertEqual(sheets['Two'].pictures[0].ext, 'png')

    def test_not_a_workbook(self):
        with self.assertRaises(WeldReportError):
            read_weld_report(io.BytesIO(b'%PDF-1.4 not a workbook'))


class ReadWeldReportTests(unittest.TestCase):
    def setUp(self):
        self.data = read_weld_report(make_xlsx(weld_form_sheets(), {'Indication ##': [(png(), 0, 12, 20, 50)]}), 'job.xlsx')

    def test_header_instrument_material_and_calibration(self):
        values = self.data['report']
        self.assertEqual((values['document_filename'], values['report_date'], values['client'], values['procedure_rev']),
                         ('PPI-31-37575-W5&W6-6inch', '2026-09-28', 'Flint Hills Resources', '9.0'))
        self.assertEqual((values['inst_name'], values['inst_serial'], values['inst_scan_speed']), ('Omniscan X3', 'QC-0030383', '≤2in/s'))
        self.assertEqual((values['pipe_size'], values['cal_std_serial'], values['item_sch_nom'], values['add1_block_type']),
                         ('6in Sch 40', '19019', 'Sch 40 / 0.280"', '10 Step'))
        self.assertEqual((values['tcg_thickness'], values['tcg_amplitude']), ('0.280', '80%'))
        self.assertEqual((values['cal_time_initial'], values['cal_time_check1'], values['cal_time_out']), ('0700', 'Accept', '0900'))
        self.assertEqual((values['weld_technician'], values['weld_reviewer_cert']), ('Lucas Jennings', 'UT II'))

    def test_probe_and_group_columns(self):
        probes = self.data['probes']
        self.assertEqual([(p['kind'], p['label']) for p in probes],
                         [('paut', '90°'), ('na', '270°'), ('conv_long', '0°'), ('conv_shear', 'Trans')])
        self.assertEqual((probes[0]['model'], probes[0]['serial'], probes[2]['serial']), ('10L32-A1', 'Y2037', '1345425'))
        self.assertEqual(probes[2]['wedge_model'], '')   # no wedge on the 0°: printed N/A by the output
        groups = self.data['groups']
        self.assertEqual([(g['probe'], g['not_applicable'], g['label']) for g in groups],
                         [(0, False, ''), (None, True, ''), (None, True, ''), (2, False, '0°'), (3, False, '')])
        self.assertEqual((groups[0]['angles'], groups[0]['reference_db'], groups[3]['angle_increment']),
                         ('42.0° - 73.0°', '10.6 dB', ''))

    def test_results_from_the_report_and_continuation_pages(self):
        rows = self.data['rows']
        self.assertEqual([r[0] for r in rows], ['W5', '', 'W6', 'W7'])
        self.assertEqual(rows[0][:4], ['W5', 'RJA4201', '0.475', '0.800'])
        self.assertEqual((rows[0][15], rows[0][16], rows[0][17]), ('LOF', 'Accept', 'Passes per B31.3'))
        self.assertEqual((rows[1][2], rows[1][15], rows[1][16]), ('0.875', 'Slag', 'Reject'))
        self.assertEqual((rows[2][16], rows[3][9], rows[3][15]), ('Accept', '1.250', 'Porosity'))

    def test_indication_pages(self):
        self.assertEqual([(p['weld'], p['number'], p['ext']) for p in self.data['indications']], [('W5', 2, 'png')])

    def test_not_the_weld_form(self):
        with self.assertRaises(WeldReportError):
            read_weld_report(make_xlsx({'Summary': {'A1': 'Short Form'}}))
        moved = weld_form_sheets()
        for ref in ('A7', 'E16', 'J16'):
            moved['Report'].pop(ref)
        with self.assertRaisesRegex(WeldReportError, 'laid out'):
            read_weld_report(make_xlsx(moved))


class BuildFromReportTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def workbook(self, sheets=None):
        return make_xlsx(sheets or weld_form_sheets(), {'Indication ##': [(png('blue'), 0, 12, 20, 50)]})

    def test_the_report_with_its_columns_rows_and_pictures(self):
        report, notes, _ = import_weld_report(self.workbook(), 'job.xlsx')
        self.assertEqual((report.report_type, report.document_filename, report.report_date, report.location),
                         ('paut_weld', 'PPI-31-37575-W5&W6-6inch', date(2026, 9, 28), 'West of Cooling Tower 5'))
        self.assertEqual(report.sensitivity_block.pipe_size, '6in Sch 40')   # the library's (seeded) block
        self.assertEqual(report.pipe_size, '6in Sch 40')
        self.assertEqual([(p.kind, p.label) for p in report.probes.all()],
                         [('paut', '90°'), ('na', '270°'), ('conv_long', '0°'), ('conv_shear', 'Trans')])
        groups = list(report.groups.all())
        self.assertEqual([g.probe.order if g.probe else None for g in groups], [0, None, None, 2, 3])
        self.assertTrue(groups[1].not_applicable)
        _, rows = report_results(report)
        self.assertEqual([r[0] for r in rows], ['W5', '', 'W6', 'W7'])
        # indications carry a key after their row; W5's 2nd (its offset row) has the Indication page's picture
        keys = [r[18] if len(r) > 18 else '' for r in rows]
        self.assertTrue(keys[0] and keys[1] and keys[3])
        self.assertEqual(keys[2], '')
        image = report.images.get()
        self.assertEqual((image.kind, image.scan_id), (ReportImage.INDICATION, keys[1]))
        self.assertEqual(notes, [])

    def test_the_output_prints_what_was_read(self):
        report, _, _ = import_weld_report(self.workbook(), 'job.xlsx')
        pages = weld_pages(report)
        cells = pages.report
        self.assertEqual((cells['X2'], cells['C7'], cells['F15'], cells['H15'], cells['L18'], cells['F34']),
                         ('PPI-31-37575-W5&W6-6inch', 'Flint Hills Resources', 'PAUT 1: Olympus 10L32-A1',
                          '0deg 1: D791', '42.0° - 73.0°', '0700'))
        self.assertEqual((cells['A41'], cells['D42'], cells['Q42'], cells['A44']), ('W5', '0.875', 'Slag', 'W6'))
        self.assertEqual([(i.weld_id, i.number) for i in pages.indications], [('W5', 2)])

    def test_defaults_fill_what_the_report_leaves_blank(self):
        from reports.models import ReportDefaults
        defaults = ReportDefaults.objects.create(name='Std', report_type='paut_weld',
                                                 report_values={'client': 'Someone else', 'exam_code': 'From defaults',
                                                                'address': ''})
        sheets = weld_form_sheets()
        sheets['Report'].pop('C11')
        report, _, _ = import_weld_report(self.workbook(sheets), 'job.xlsx', defaults)
        self.assertEqual((report.client, report.exam_code), ('Flint Hills Resources', 'From defaults'))

    def test_notes_for_what_the_form_cant_hold(self):
        sheets = weld_form_sheets()
        sheets['Report'].update({'N15': 'PAUT 2: Olympus 5L32-A32', 'N16': 'Sectorial', 'Q36': '3.00'})
        _, notes, _ = import_weld_report(self.workbook(sheets), 'job.xlsx')
        self.assertTrue(any("Group 2 is on probe 'PAUT 2: Olympus 5L32-A32'" in n for n in notes))
        self.assertTrue(any("TCG's 4th point" in n for n in notes))


class StartFromReportViewTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def post(self, upload, **extra):
        data = {'type': 'paut_weld', 'source': 'report', 'folder_mode': 'none', 'defaults': '', **extra}
        if upload is not None:
            data['existing_report'] = upload
        return self.client.post(reverse('start-from-files'), data)

    def test_upload_opens_the_guided_editor(self):
        workbook = make_xlsx(weld_form_sheets()).getvalue()
        response = self.post(SimpleUploadedFile('PPI-31-37575.xlsx', workbook))
        report = Report.objects.get()
        self.assertRedirects(response, f"{reverse('create-report')}?loaded={report.pk}&wizard=1", fetch_redirect_response=False)
        self.assertEqual(report.client, 'Flint Hills Resources')
        self.assertEqual(report.job_folder, '')

    def test_a_pdf_or_nothing_is_refused(self):
        response = self.post(SimpleUploadedFile('report.pdf', b'%PDF-1.4'))
        self.assertRedirects(response, f"{reverse('start-from-files')}?type=paut_weld&source=report", fetch_redirect_response=False)
        self.assertFalse(Report.objects.exists())
        self.post(None)
        self.assertFalse(Report.objects.exists())

    def test_the_page_offers_it_for_weld_reports(self):
        page = self.client.get(reverse('start-from-files') + '?type=paut_weld&source=report').content.decode()
        self.assertIn('name="existing_report"', page)
        self.assertIn('id="source-report" value="report" checked', page)
        long_form = self.client.get(reverse('start-from-files') + '?type=paut_long').content.decode()
        self.assertNotIn('name="existing_report"', long_form)   # no reader for the Long Form's Word report


REFERENCE = os.path.expanduser('~/Desktop/Reports/001 Welds/PPI-31-37575-FW5&6/PPI-31-37575-W5&W6-6inch.xlsx')


@unittest.skipUnless(os.path.exists(REFERENCE), 'the reference weld report is not on this PC')
class ReferenceReportTests(unittest.TestCase):
    def test_the_reference_report_reads(self):
        data = read_weld_report(REFERENCE)
        self.assertEqual(data['report']['work_order'], 'WO5757163')
        self.assertEqual([r[0] for r in data['rows']], ['W5', 'W6'])
        self.assertEqual(data['rows'][0][3], '0.800')
        self.assertEqual(data['groups'][3]['amplitude_range'], '800%')
        self.assertEqual(len(results_layout(data['rows'])[0]), 2)
