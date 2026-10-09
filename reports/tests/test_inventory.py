"""Scope and probe inventory from a weld report workbook's Scope and Encoder / All Probes sheets."""
import datetime
import io
import os
import tempfile
import zipfile
from xml.sax.saxutils import escape

from django.core.management import call_command
from django.test import TestCase

from equipment.inventory import apply_inventory, catalogue_name, read_probes, read_scopes
from equipment.models import Probe, ProbeModel, Scope

SCOPES = [
    ['Unit', 'Manufacturer', 'Model', 'Serial #', 'Cal Due Date', 'Pulser Model #', 'Pulsar Serial #',
     'Pulsar Cal Due Date', 'Software Version', 'Scanner Type', 'Column11', 'Analysis Software', 'Software Version2'],
    ['Omniscan X3', 'Olympus', 'X3', 'QC-0030383', 46403, '32:128', 'N/A', 'N/A', '5.20.0', 'SAUT', '', 'OmniPC', '6.3.0'],
    ['Omniscan MX2', 'Olympus', 'Omniscan MX2', ' \tOMNI2-104208', 46403, 'OMNI-M2-PA32128PR', 'QC-013106',
     '1/16/2026', 'MXU - 4.4R4', 'SAUT', '', 'OmniPC', '6.3.0'],
    [],
    ['', 'Manufacturer', '', 'Olympus'],   # the lookup panel below the table isn't an instrument
]
PROBES = [
    ['', '', '', 'Current', '', 'Pervious'],
    ['Manufacturer', 'Probe Type', 'Serial Number', 'Inactive', 'Defective', 'Inactive', 'Defective', 'Obtainable'],
    [],
    ['Olympus', '7.5LCCEV35 A15 ', 'T2802', 0, 0, 0, 0, 'Y'],
    ['Olympus', '10L32 A10', 'U2040', 11, 2, 'N/A', 'N/A', 'N'],
    ['Olympus', '4M 16X2 A27', 'U2346', 0, 0, 0, 0, 'Y'],
]


def column(n):
    letters = ''
    while n:
        n, rest = divmod(n - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def workbook(sheets):
    """A minimal .xlsx with these {name: rows} sheets (text as shared strings, numbers as numbers)."""
    strings, sheet_xml = [], {}
    for index, (name, rows) in enumerate(sheets.items(), start=1):
        cells = []
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row, start=1):
                if value == '':
                    continue
                ref = f'{column(c)}{r}'
                if isinstance(value, str):
                    strings.append(value)
                    cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
                else:
                    cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        sheet_xml[index] = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                            f'<row>{"".join(cells)}</row></sheetData></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + ''.join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings) + '</sst>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, name in enumerate(sheets, start=1)) + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + ''.join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in sheet_xml)
                   + '</Relationships>')
        for i, xml in sheet_xml.items():
            z.writestr(f'xl/worksheets/sheet{i}.xml', xml)
    return buf.getvalue()


class InventoryImportTests(TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix='.xlsx')
        with os.fdopen(handle, 'wb') as f:
            f.write(workbook({'Scope and Encoder': SCOPES, 'All Probes 2025': PROBES}))
        self.addCleanup(os.remove, self.path)

    def test_scopes(self):
        x3, mx2 = read_scopes(self.path)
        self.assertEqual((x3['name'], x3['serial_number'], x3['calibration_due_date']),
                         ('Omniscan X3', 'QC-0030383', datetime.date(2027, 1, 16)))
        self.assertEqual((x3['module_model'], x3['module_serial'], x3['module_cal_due']), ('32:128', '', None))
        self.assertEqual((x3['instrument_software_version'], x3['software'], x3['software_version']),
                         ('5.20.0', 'OmniPC', '6.3.0'))
        self.assertEqual((mx2['serial_number'], mx2['module_cal_due']), ('OMNI2-104208', datetime.date(2026, 1, 16)))

    def test_probes(self):
        probes = read_probes(self.path)
        self.assertEqual([p['serial_number'] for p in probes], ['T2802', 'U2040', 'U2346'])
        self.assertEqual(probes[0]['model'], '7.5LCCEV35 A15')
        self.assertEqual((probes[1]['inactive_elements'], probes[1]['defective_elements'],
                          probes[1]['previous_inactive_elements'], probes[1]['calibration_obtainable']), (11, 2, None, False))

    def test_inventory_spelling_of_ccev_probes(self):
        self.assertEqual(catalogue_name('7.5LCCEV35 A15'), '7.5CCEV35 A15')
        self.assertEqual(catalogue_name('10L32 A10'), '10L32 A10')

    def test_command_adds_then_updates_and_links_the_catalogue(self):
        ProbeModel.objects.get_or_create(model='7.5CCEV35-A15', defaults={'series': 'A15', 'frequency': 7.5, 'elements': 16})
        call_command('import_inventory', self.path, stdout=io.StringIO())
        call_command('import_inventory', self.path, stdout=io.StringIO())   # again: updates, no duplicates
        self.assertEqual(Scope.objects.count(), 2)
        self.assertEqual(Probe.objects.count(), 3)
        probe = Probe.objects.get(serial_number='T2802')
        self.assertEqual((probe.catalogue.model, probe.frequency, probe.elements), ('7.5CCEV35-A15', '7.5 MHz', '16'))
        self.assertIsNone(Probe.objects.get(serial_number='U2346').catalogue)   # series not in the catalogue
        self.assertEqual(Scope.objects.get(serial_number='OMNI2-104208').module_serial, 'QC-013106')


class InventoryYearAndSerialTests(TestCase):
    def path_for(self, sheets):
        handle, path = tempfile.mkstemp(suffix='.xlsx')
        with os.fdopen(handle, 'wb') as f:
            f.write(workbook(sheets))
        self.addCleanup(os.remove, path)
        return path

    def test_the_latest_all_probes_sheet_is_read(self):
        newer = PROBES[:3] + [['Olympus', '10L32 A10', 'V9999', 0, 0, 0, 0, 'Y']]
        path = self.path_for({'All Probes 2025': PROBES, 'All Probes 2026': newer})
        self.assertEqual([p['serial_number'] for p in read_probes(path)], ['V9999'])

    def test_scopes_without_a_serial_number_are_not_merged(self):
        blank = {'name': '', 'manufacturer': 'Evident', 'model': 'X3', 'serial_number': '', 'calibration_due_date': None}
        apply_inventory([dict(blank, name='One'), dict(blank, name='Two')], [])
        self.assertEqual(sorted(Scope.objects.values_list('name', flat=True)), ['One', 'Two'])


class LibraryScopeTests(TestCase):
    """An .nde file or saved setup's instrument, completed from the scope library by serial number."""

    def setUp(self):
        Scope.objects.create(name='Omniscan X3', manufacturer='Olympus', model='X3', serial_number='QC-0030383',
                             calibration_due_date=datetime.date(2027, 1, 16), module_model='32:128',
                             instrument_software_version='5.18.1', scanner_type='SAUT', software='OmniPC',
                             software_version='6.3.0')

    def test_matching_serial_fills_the_library_items(self):
        from equipment.inventory import with_library_scope
        from reports.weld_columns import columns_from_setup
        values, scope = with_library_scope({'scope_platform': 'OmniScan X3', 'scope_model': 'OmniScan X3 - 32:128PR',
                                            'scope_serial': ' qc-0030383', 'manufacturer': 'Evident',
                                            'software_version': '5.20.0'})
        self.assertEqual(scope.serial_number, 'QC-0030383')
        instrument = columns_from_setup(values)['instrument']
        self.assertEqual((instrument['inst_name'], instrument['inst_manufacturer'], instrument['inst_model']),
                         ('Omniscan X3', 'Olympus', 'X3'))
        self.assertEqual((instrument['inst_cal_due'], instrument['inst_module_model'], instrument['inst_module_serial'],
                          instrument['inst_module_cal_due']), ('1/16/2027', '32:128', 'N/A', 'N/A'))
        self.assertEqual((instrument['inst_scanner_type'], instrument['inst_analysis_software'],
                          instrument['inst_analysis_software_version']), ('SAUT', 'OmniPC', '6.3.0'))
        self.assertEqual(instrument['inst_software_version'], '5.20.0')   # the file's own, not the library's
        self.assertEqual(columns_from_setup(values)['probe']['make'], 'Evident')   # the probe's maker isn't the scope's

    def test_unknown_serial_leaves_the_file_values(self):
        from equipment.inventory import with_library_scope
        values = {'scope_serial': 'QC-9999999', 'scope_model': 'OmniScan X3'}
        self.assertEqual(with_library_scope(values), (values, None))

    def test_nde_import_names_the_library_scope(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        from reports.tests.test_nde_upload import FIXTURE, make_nde, sample_setup
        setup = sample_setup()
        setup['acquisitionUnits'][0]['serialNumber'] = 'QC-0030383'
        data = self.client.post(reverse('nde-columns'), {
            'nde_file': SimpleUploadedFile('scan.nde', make_nde(setup, FIXTURE['properties']))}).json()
        column = data['columns'][0]
        self.assertEqual(column['scope'], 'Omniscan X3 QC-0030383')
        self.assertEqual(column['instrument']['inst_cal_due'], '1/16/2027')
