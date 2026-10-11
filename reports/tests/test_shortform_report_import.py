"""Guided Creation from an existing Short Form: the corrosion form's .xlsx read back into a report."""
import glob
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from reports.models import Report, ReportImage, TextSnippet
from reports.results import report_results
from reports.services.corrosion_report import corrosion_pages
from reports.services.shortform_report_import import (
    ShortFormError, import_short_form, read_short_form, split_block, split_serial,
)
from reports.services.xlsx_reader import read_workbook
from reports.tests.test_weld_report_import import make_xlsx, png, weld_form_sheets

DESCRIPTION = 'HydroFORM – HydroFORM utilizes a water column to couple the probe to the part.'


def short_form_sheets():
    """A Short Form as the technicians fill it: Summary, a Setup Information page, a drawing page,
    the Thickness Table and an Images page (two captions)."""
    return {
        'Summary': {
            'B2': 'Phased Array Ultrasonic Examinations on 11V58A', 'B5': 'Client Company:', 'L5': 'Flint Hills Resources',
            'V5': 'Test Date:', 'AA5': date(2026, 3, 11), 'AE5': 'Report Date:', 'AJ5': date(2026, 3, 14),
            'B6': 'Location:', 'L6': 'Rosemount, MN', 'V6': 'Procedure:', 'AA6': '100-UT-020 Rev. 9.0',
            'AJ6': 'Total Pages:', 'AO6': 5, 'B7': 'Client Work Order:', 'L7': 'WO5387803',
            'V7': 'Unit / Equipment:', 'AC7': '11V58A', 'B8': 'Technician(s) /\nCertification Level:',
            'I8': 'Lucas Jennings\nUltrasonics Level II', 'V8': 'Reviewed by:', 'AC8': 'Sky Tervo PAUT Lvl II',
            'B10': 'Examination Scope', 'B11': 'Corrosion mapping of the shell.',
            # a hand-made copy: the boxes a row up from the form's
            'B15': 'Summary of Results', 'B16': 'No significant wall loss.', 'B44': 'Notes', 'B45': 'Scaffold needed.',
        },
        'Setup Information': {
            'B2': 'Setup Details', 'V2': 'Method Information:', 'AG2': 'HydroFORM', 'B5': DESCRIPTION,
            'B7': 'Surface Preparation:', 'J7': 'Bare metal', 'Z7': '70°F', 'AJ7': '0.1"', 'AN7': '0.5"',
            'J8': 'Carbon Steel', 'Z8': '350°F', 'AH8': 'Olympus X3-64\nSn:QC-0082535',
            'L9': 'Carbon Steel Mini PACS\nSN: 55386', 'AB9': '7.5L64 I4\nSN: T0866',
        },
        'Horizontal Drawing': {'B2': 'Drawing', 'N2': '11V58A'},
        'Vertical Drawing': {'B2': 'Drawing', 'N2': '11V58A'},   # unused: no picture
        'Thickness Table': {
            'B2': 'Results', 'B5': 'Scan ID', 'C5': 'Axial Start / Stop', 'D5': 'Circ Start / Stop',
            'E5': 'Minimum Thickness\n(inches)', 'F5': 'Average Thickness (inches)', 'G5': 'Results',
            'B6': 'Circ 1 East', 'C6': '0 - 2.4"', 'D6': '15 - 82', 'E6': 0.501, 'F6': 0.515, 'G6': 'Acceptable',
            'B8': 'Circ 2 West', 'E8': 0.471, 'G8': 'Some pitting',
            'B19': 'Low Readings', 'E19': 0,
        },
        'Images': {'B19': 'North strip', 'K19': 'Corrosion between 25" and 55".', 'B43': 'N/A', 'K43': 'N/A'},
        'Formulas': {'B1': 'HydroFORM'},
        'Sheet1': {'C8': 'North'},
    }


def short_form_pictures():
    return {
        'Setup Information': [(png('green'), 1, 9, 40, 43)],
        'Horizontal Drawing': [(png('blue', (60, 30)), 1, 4, 45, 37), (png('red'), 1, 20, 5, 25)],
        'Images': [(png('yellow'), 1, 1, 44, 17)],
    }


def workbook(sheets=None, pictures=None):
    return make_xlsx(sheets or short_form_sheets(), short_form_pictures() if pictures is None else pictures)


def place_in_cell(xlsx, sheet_index, ref, picture):
    """The workbook with `picture` placed in cell `ref` of sheet n (Insert › Picture › Place in Cell)."""
    out = io.BytesIO()
    with zipfile.ZipFile(xlsx) as src, zipfile.ZipFile(out, 'w') as z:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == f'xl/worksheets/sheet{sheet_index}.xml':
                text = data.decode()
                cell = f'<c r="{ref}" t="e" vm="1"><v>#VALUE!</v></c>'
                row = ''.join(ch for ch in ref if ch.isdigit())
                text = text.replace('<sheetData>', f'<sheetData><row r="{row}">{cell}</row>', 1)
                data = text.encode()
            z.writestr(item, data)
        rd = 'http://schemas.microsoft.com/office/spreadsheetml/2017/richdata'
        z.writestr('xl/metadata.xml',
                   '<?xml version="1.0"?><metadata xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   f'xmlns:xlrd="{rd}"><futureMetadata name="XLRICHVALUE" count="1"><bk><extLst><ext uri="x">'
                   '<xlrd:rvb i="0"/></ext></extLst></bk></futureMetadata>'
                   '<valueMetadata count="1"><bk><rc t="1" v="0"/></bk></valueMetadata></metadata>')
        z.writestr('xl/richData/rdrichvaluestructure.xml',
                   f'<?xml version="1.0"?><rvStructures xmlns="{rd}" count="1"><s t="_localImage">'
                   '<k n="_rvRel:LocalImageIdentifier" t="i"/><k n="CalcOrigin" t="i"/></s></rvStructures>')
        z.writestr('xl/richData/rdrichvalue.xml',
                   f'<?xml version="1.0"?><rvData xmlns="{rd}" count="1"><rv s="0"><v>0</v><v>5</v></rv></rvData>')
        z.writestr('xl/richData/richValueRel.xml',
                   '<?xml version="1.0"?><richValueRels xmlns="http://schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><rel r:id="rId1"/></richValueRels>')
        z.writestr('xl/richData/_rels/richValueRel.xml.rels',
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                   'Target="../media/incell1.png"/></Relationships>')
        z.writestr('xl/media/incell1.png', picture)
    out.seek(0)
    return out


class SplitTests(unittest.TestCase):
    def test_serials(self):
        self.assertEqual(split_serial('Olympus X3-64\nSn:QC-0082535'), ('Olympus X3-64', 'QC-0082535'))
        self.assertEqual(split_serial('Stainless Mini PACS Sn:39246'), ('Stainless Mini PACS', '39246'))
        self.assertEqual(split_serial('OmniScan X3 64 - 64:128PR\nSN: QC-0084893'), ('OmniScan X3 64 - 64:128PR', 'QC-0084893'))
        self.assertEqual(split_serial('7.5L16A15'), ('7.5L16A15', ''))
        # as the technicians type them on hand-made copies
        self.assertEqual(split_serial('Epoch 650 /\nSN: 190846904'), ('Epoch 650', '190846904'))
        self.assertEqual(split_serial('Carbon Steel 10 Step /\nSN#: 51349'), ('Carbon Steel 10 Step', '51349'))
        self.assertEqual(split_serial('7.5L64 I4 HydroFORM S# Z8032'), ('7.5L64 I4 HydroFORM', 'Z8032'))
        self.assertEqual(split_serial('Carbon Steel 10-step\n S#: 51349'), ('Carbon Steel 10-step', '51349'))
        self.assertEqual(split_serial('Carbon Steel / 51349'), ('Carbon Steel', '51349'))
        self.assertEqual(split_serial('Carbon Steel 5-step\n51349'), ('Carbon Steel 5-step', '51349'))

    def test_people(self):
        from reports.services.shortform_report_import import _person
        self.assertEqual(_person('Sky Tervo / PAUT Lvl II'), ('Sky Tervo', 'PAUT Lvl II'))
        self.assertEqual(_person('Lucas Jennings /\nPAUT Level II'), ('Lucas Jennings', 'PAUT Level II'))
        self.assertEqual(_person('Sky Tervo PAUT Lvl II, Daire Butturff PAUT Lvl II'),
                         ('Sky Tervo PAUT Lvl II, Daire Butturff PAUT Lvl II', ''))

    def test_excel_escapes_in_text(self):
        sheets = short_form_sheets()
        sheets['Summary']['B16'] = 'No wall loss. _x000D_\n_x000D_\nNext paragraph, _x005F_x000D_ as typed.'
        self.assertEqual(read_short_form(workbook(sheets), 'job.xlsx')['report']['executive_summary'],
                         'No wall loss. \n\nNext paragraph, _x000D_ as typed.')

    def test_blocks(self):
        self.assertEqual(split_block('Carbon Steel Mini PACS'), ('Carbon Steel', 'Mini PACS'))
        self.assertEqual(split_block('Stainless IIW'), ('Stainless', 'IIW'))
        self.assertEqual(split_block('Carbon Steel 10-Step'), ('Carbon Steel', '10-Step'))
        self.assertEqual(split_block('Carbon Steel AUT Cal Block'), ('Carbon Steel', 'AUT Cal Block'))
        self.assertEqual(split_block('Navships 1018 CS'), ('Navships 1018 CS', ''))
        self.assertEqual(split_block('Carbon Steel'), ('Carbon Steel', ''))


class ReadShortFormTests(unittest.TestCase):
    def setUp(self):
        self.data = read_short_form(workbook(), 'job.xlsx')

    def test_summary(self):
        values = self.data['report']
        self.assertEqual((values['client'], values['work_order'], values['equipment_id'], values['test_date'],
                          values['report_date']),
                         ('Flint Hills Resources', 'WO5387803', '11V58A', '2026-03-11', '2026-03-14'))
        self.assertEqual((values['procedure'], values['procedure_rev']), ('100-UT-020', '9.0'))
        self.assertEqual((values['weld_technician'], values['weld_technician_cert']), ('Lucas Jennings', 'Ultrasonics Level II'))
        self.assertEqual((values['weld_reviewer'], values['weld_reviewer_cert']), ('Sky Tervo PAUT Lvl II', ''))
        self.assertEqual((values['examination_scope'], values['executive_summary'], values['notes']),
                         ('Corrosion mapping of the shell.', 'No significant wall loss.', 'Scaffold needed.'))

    def test_setup_page(self):
        [setup] = self.data['setups']
        self.assertEqual({k: setup['values'][k] for k in ('title', 'tr_min', 'inspection_temp', 'scope_model', 'scope_serial',
                                                          'cal_material', 'cal_block_type', 'cal_block_serial',
                                                          'transducer_model', 'transducer_serial')},
                         {'title': 'HydroFORM', 'tr_min': '0.1"', 'inspection_temp': '350°F', 'scope_model': 'Olympus X3-64',
                          'scope_serial': 'QC-0082535', 'cal_material': 'Carbon Steel', 'cal_block_type': 'Mini PACS',
                          'cal_block_serial': '55386', 'transducer_model': '7.5L64 I4', 'transducer_serial': 'T0866'})
        self.assertEqual(setup['description'], DESCRIPTION)
        self.assertEqual(setup['ext'], 'png')

    def test_drawings_thickness_and_images(self):
        self.assertEqual([d['sheet'] for d in self.data['drawings']], ['Horizontal Drawing'])   # the blank page left out
        self.assertEqual(self.data['rows'], [['Circ 1 East', '0 - 2.4"', '15 - 82', '0.501', '0.515', 'Acceptable'],
                                             ['Circ 2 West', '', '', '0.471', '', 'Some pitting']])
        self.assertEqual([(i['caption'], i['description'], i['ext']) for i in self.data['images']],
                         [('North strip', 'Corrosion between 25" and 55".', 'png')])
        self.assertEqual(self.data['notes'], ["Sheet1 isn't part of the form; left out."])

    def test_a_hand_made_table_with_its_own_columns(self):
        sheets = short_form_sheets()
        sheets['Thickness Table'] = {'B5': 'Weld ID', 'C5': 'Location', 'D5': 'length', 'E5': 'height', 'F5': 'Notes',
                                     'B6': 'Nozzle F2', 'C6': "2 o'clock", 'D6': '0.4"', 'E6': '0.045"', 'F6': 'ID connected'}
        data = read_short_form(workbook(sheets), 'job.xlsx')
        self.assertEqual(data['rows'], [['Nozzle F2', "2 o'clock", '0.4"', '0.045"', '', 'ID connected']])   # notes last
        self.assertTrue(any('its own headings (Weld ID, Location, length, height, Notes)' in n for n in data['notes']))

    def test_not_a_short_form(self):
        with self.assertRaisesRegex(ShortFormError, 'no Short Form Summary page'):
            read_short_form(make_xlsx(weld_form_sheets()), 'weld.xlsx')
        sheets = short_form_sheets()
        sheets['Summary'] = {'B2': 'Title', 'A1': 'Examination Scope', 'A2': 'Client Company'}
        with self.assertRaisesRegex(ShortFormError, "isn't laid out like the Short Form"):
            read_short_form(workbook(sheets), 'odd.xlsx')

    def test_pictures_placed_in_cells(self):
        sheets = short_form_sheets()
        images = list(sheets).index('Images') + 1
        xlsx = place_in_cell(workbook(sheets, {}), images, 'B26', png('purple'))
        [picture] = read_workbook(xlsx)['Images'].pictures
        self.assertEqual((picture.row, picture.col, picture.ext), (26, 2, 'png'))
        xlsx.seek(0)
        data = read_short_form(xlsx, 'job.xlsx')
        self.assertEqual([i['caption'] for i in data['images'] if i['picture']], [''])   # under 'North strip', above N/A


class BuildShortFormTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def test_the_report(self):
        report, notes, _ = import_short_form(workbook(), 'Corrosion-11V58A.xlsx')
        self.assertEqual((report.report_type, report.document_filename, report.test_date, report.report_date, report.client),
                         ('paut_corrosion', 'Corrosion-11V58A', date(2026, 3, 11), date(2026, 3, 14), 'Flint Hills Resources'))
        setup = report.setups.get()
        self.assertEqual((setup.title, setup.scope_serial, setup.cal_block_type), ('HydroFORM', 'QC-0082535', 'Mini PACS'))
        self.assertEqual(setup.images.count(), 1)
        snippet = setup.method_description
        self.assertEqual((snippet.kind, snippet.title, snippet.body),
                         (TextSnippet.TECHNIQUE, 'HydroFORM', 'HydroFORM utilizes a water column to couple the probe to the part.'))
        self.assertEqual([(i.kind, i.caption) for i in report.images.order_by('order')],
                         [(ReportImage.DRAWING, ''), (ReportImage.SCAN, 'North strip')])
        _, rows = report_results(report)
        self.assertEqual([r[0] for r in rows], ['Circ 1 East', 'Circ 2 West'])
        self.assertTrue(any('added as' in n for n in notes))

    def test_a_library_description_is_reused(self):
        snippet = TextSnippet.objects.create(kind=TextSnippet.TECHNIQUE, name='HydroFORM test', title='HydroFORM',
                                             body='HydroFORM utilizes a water column to couple the probe to the part.')
        report, notes, _ = import_short_form(workbook(), 'job.xlsx')
        self.assertEqual(report.setups.get().method_description, snippet)
        self.assertFalse(any('added as' in n for n in notes))

    def test_the_output_prints_what_was_read(self):
        report, _, _ = import_short_form(workbook(), 'job.xlsx')
        pages = corrosion_pages(report)
        summary = pages.summary
        self.assertEqual((summary['B2'], summary['L7'], summary['AA6'], summary['AH6'], summary['I8'], summary['B18']),
                         ('Phased Array Ultrasonic Examinations on 11V58A', 'WO5387803', '100-UT-020', '9.0',
                          'Lucas Jennings\nUltrasonics Level II', 'No significant wall loss.'))
        cells = pages.setups[0].cells
        self.assertEqual((cells['B5'], cells['AH8'], cells['L9'], cells['AB9']),
                         (DESCRIPTION, 'Olympus X3-64\nSN: QC-0082535', 'Carbon Steel Mini PACS\nSN: 55386', '7.5L64 I4\nSN: T0866'))
        self.assertTrue(pages.setups[0].picture)   # the page's picture, as the setup has no .nde
        self.assertEqual(len(pages.drawings), 1)
        self.assertEqual([[s.caption for s in page] for page in pages.images], [['North strip']])
        self.assertEqual(pages.thickness[0], ['Circ 1 East', '0 - 2.4"', '15 - 82', '0.501', '0.515', 'Acceptable'])

    def test_defaults_fill_only_what_the_file_leaves_blank(self):
        from reports.models import ReportDefaults
        defaults = ReportDefaults.objects.create(
            name='Std', report_type='paut_corrosion',
            report_values={'weld_reviewer': 'Default Reviewer', 'weld_reviewer_cert': 'UT III',
                           'weld_technician_cert': 'Default cert', 'examination_scope': 'Default scope'})
        sheets = short_form_sheets()
        sheets['Summary'].pop('B11')
        sheets['Summary']['I8'] = 'Daire Butturff'   # no certification typed: not the defaults' beside this name
        report, _, _ = import_short_form(workbook(sheets), 'job.xlsx', defaults)
        self.assertEqual((report.weld_technician, report.weld_technician_cert), ('Daire Butturff', ''))
        self.assertEqual((report.weld_reviewer, report.weld_reviewer_cert), ('Sky Tervo PAUT Lvl II', ''))
        self.assertEqual(report.examination_scope, 'Default scope')

    def test_no_setup_page(self):
        sheets = short_form_sheets()
        sheets['Setup Information'] = {'B2': 'Setup Details'}
        report, notes, _ = import_short_form(workbook(sheets, {}), 'job.xlsx')
        self.assertEqual(report.setups.count(), 1)
        self.assertTrue(any('one empty setup was added' in n for n in notes))


class StartFromShortFormViewTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def post(self, upload):
        data = {'type': 'paut_corrosion', 'source': 'report', 'folder_mode': 'none', 'defaults': ''}
        if upload is not None:
            data['existing_report'] = upload
        return self.client.post(reverse('start-from-files'), data)

    def test_upload_opens_the_guided_editor(self):
        response = self.post(SimpleUploadedFile('11V58A.xlsx', workbook().getvalue()))
        report = Report.objects.get()
        self.assertRedirects(response, f"{reverse('create-report')}?loaded={report.pk}&wizard=1", fetch_redirect_response=False)
        self.assertEqual((report.report_type, report.equipment_id), ('paut_corrosion', '11V58A'))

    def test_a_weld_report_is_refused(self):
        response = self.post(SimpleUploadedFile('weld.xlsx', make_xlsx(weld_form_sheets()).getvalue()))
        self.assertRedirects(response, f"{reverse('start-from-files')}?type=paut_corrosion&source=report",
                             fetch_redirect_response=False)
        self.assertFalse(Report.objects.exists())

    def test_the_page_offers_it(self):
        page = self.client.get(reverse('start-from-files') + '?type=paut_corrosion').content.decode()
        self.assertIn('An existing Short Form', page)
        self.assertIn('name="existing_report"', page)


REPORTS = os.path.expanduser('~/Desktop/Reports')


@unittest.skipUnless(os.path.isdir(REPORTS), 'the Reports folder is not on this PC')
class RealShortFormTests(unittest.TestCase):
    def test_every_short_form_in_the_reports_folder_reads(self):
        read = 0
        for path in glob.glob(os.path.join(REPORTS, '**', '*.xlsx'), recursive=True):
            if os.path.basename(path).startswith('~$'):
                continue
            try:
                sheets = read_workbook(path)
            except Exception:
                continue
            if 'Summary' not in sheets:
                continue
            data = read_short_form(path, os.path.basename(path))
            self.assertTrue(data['setups'], path)
            read += 1
        if not read:
            self.skipTest('no Short Form workbooks here')
