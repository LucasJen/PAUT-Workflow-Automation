"""Scope and probe inventory from a weld report workbook's Scope and Encoder / All Probes sheets."""
import datetime
import io
import os
import tempfile
import zipfile
from xml.sax.saxutils import escape

from django.core.management import call_command
from django.test import TestCase

from equipment.inventory import catalogue_name, read_probes, read_scopes
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
