"""
The equipment inventory from a weld report workbook (the 100-UTFORM-010 reference): its
"Scope and Encoder" sheet (instruments) and "All Probes <year>" sheet (serial-numbered probes with
their element checks; the latest year when there are several). Read straight from the .xlsx XML, so no Excel or extra library is needed.
`manage.py import_inventory <workbook>` applies them; a scope or probe already in the inventory
(same serial number) is updated.
"""
import datetime
import re
import zipfile
from xml.etree import ElementTree

from django.db import transaction

from .matching import match_probe
from .models import Probe, Scope

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
SCOPE_SHEET = 'Scope and Encoder'
PROBE_SHEET = 'All Probes'   # 'All Probes 2025', 'All Probes 2026'...: the name starts with this


class InventoryError(Exception):
    """The workbook or one of its sheets can't be read."""


def read_sheet(path, name, prefix=False):
    """
    {row number: {column letters: text}} of one worksheet (cached values, not formulas). With
    `prefix`, the sheet is the last (by name, so the latest year) whose name starts with `name`.
    """
    try:
        book = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise InventoryError(f"Can't open {path}: {e}")
    with book:
        strings = []
        if 'xl/sharedStrings.xml' in book.namelist():
            for item in ElementTree.fromstring(book.read('xl/sharedStrings.xml')).findall('m:si', NS):
                strings.append(''.join(t.text or '' for t in item.iter(f"{{{NS['m']}}}t")))
        workbook = ElementTree.fromstring(book.read('xl/workbook.xml'))
        sheets = list(workbook.find('m:sheets', NS))
        if prefix:
            sheet = max((s for s in sheets if s.get('name', '').startswith(name)), key=lambda s: s.get('name'),
                        default=None)
        else:
            sheet = next((s for s in sheets if s.get('name') == name), None)
        if sheet is None:
            raise InventoryError(f'The workbook has no "{name}{" …" if prefix else ""}" sheet.')
        rels = ElementTree.fromstring(book.read('xl/_rels/workbook.xml.rels'))
        target = next(r.get('Target') for r in rels if r.get('Id') == sheet.get(f"{{{NS['r']}}}id"))
        xml = ElementTree.fromstring(book.read('xl/' + target.lstrip('/').removeprefix('xl/')))
    rows = {}
    for cell in xml.iter(f"{{{NS['m']}}}c"):
        value = cell.find('m:v', NS)
        if value is None or value.text is None:
            continue
        text = strings[int(value.text)] if cell.get('t') == 's' else value.text
        col, row = re.match(r'([A-Z]+)(\d+)', cell.get('r')).groups()
        rows.setdefault(int(row), {})[col] = text.strip()
    return rows


def _blank(text):
    return '' if (text or '').strip().upper() in ('', 'N/A', 'NA') else text.strip()


def _date(text):
    """An Excel date serial (46403) or m/d/yyyy text -> date; N/A or blank -> None."""
    text = _blank(text)
    if not text:
        return None
    if re.fullmatch(r'\d+(\.0+)?', text):
        return datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(text)))
    for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _count(text):
    text = _blank(text)
    return int(float(text)) if re.fullmatch(r'\d+(\.\d+)?', text) else None


def read_scopes(path):
    """The instruments of the Scope and Encoder sheet's table (Unit, Manufacturer, Model, ...)."""
    rows = read_sheet(path, SCOPE_SHEET)
    header = rows.get(1, {})
    if header.get('A') != 'Unit' or header.get('D') != 'Serial #':
        raise InventoryError(f'The "{SCOPE_SHEET}" sheet doesn\'t start with its Unit / Serial # table.')
    scopes = []
    for number in sorted(rows):
        row = rows[number]
        if number == 1 or not row.get('A'):
            if number > 1:
                break   # the table ends at its first empty row (a lookup panel follows below)
            continue
        scopes.append({
            'name': row.get('A', ''),
            'manufacturer': row.get('B', ''),
            'model': row.get('C', ''),
            'serial_number': row.get('D', ''),
            'calibration_due_date': _date(row.get('E')),
            'module_model': _blank(row.get('F')),
            'module_serial': _blank(row.get('G')),
            'module_cal_due': _date(row.get('H')),
            'instrument_software_version': _blank(row.get('I')),
            'scanner_type': _blank(row.get('J')),
            'software': _blank(row.get('L')),
            'software_version': _blank(row.get('M')),
        })
    return scopes


def read_probes(path):
    """The probes of the All Probes sheet: make, model, S/N, element checks and calibration."""
    rows = read_sheet(path, PROBE_SHEET, prefix=True)
    probes = []
    for number in sorted(rows):
        row = rows[number]
        if not row.get('C') or row.get('C') == 'Serial Number':
            continue
        obtainable = _blank(row.get('H')).upper()[:1]
        probes.append({
            'manufacturer': row.get('A', ''),
            'model': re.sub(r'\s+', ' ', row.get('B', '')),
            'serial_number': row.get('C', ''),
            'inactive_elements': _count(row.get('D')),
            'defective_elements': _count(row.get('E')),
            'previous_inactive_elements': _count(row.get('F')),
            'previous_defective_elements': _count(row.get('G')),
            'calibration_obtainable': {'Y': True, 'N': False}.get(obtainable),
        })
    return probes


def catalogue_name(model):
    """The inventory's spelling of a probe model as the catalogue writes it: '7.5LCCEV35 A15' -> '7.5CCEV35 A15'."""
    return re.sub(r'(?i)(\d)LCCEV', r'\1CCEV', model or '')


@transaction.atomic
def apply_inventory(scopes, probes):
    """Adds or updates (by serial number) the scopes and probes; returns counts per kind. One without a
    serial number is always added: there's nothing to tell it apart from the others with none."""
    counts = {'scopes added': 0, 'scopes updated': 0, 'probes added': 0, 'probes updated': 0, 'probes linked': 0}
    for values in scopes:
        serial = values['serial_number'].strip()
        scope = Scope.objects.filter(serial_number=serial).first() if serial else None
        counts['scopes updated' if scope else 'scopes added'] += 1
        scope = scope or Scope()
        for name, value in values.items():
            setattr(scope, name, value)
        scope.save()
    for values in probes:
        serial = values['serial_number'].strip()
        probe = Probe.objects.filter(serial_number=serial).first() if serial else None
        counts['probes updated' if probe else 'probes added'] += 1
        probe = probe or Probe()
        for name, value in values.items():
            setattr(probe, name, value)
        if probe.catalogue_id is None:
            probe.catalogue = match_probe({'model': catalogue_name(probe.model)}).item
        if probe.catalogue_id is not None:
            counts['probes linked'] += 1
            probe.fill_from_catalogue()
        probe.save()
    return counts


# ── The library's details for an instrument a file or setup names by serial number ──

def _serial_key(serial):
    return re.sub(r'\s+', '', serial or '').upper()


def library_scope(serial):
    """The inventory scope with this serial number (ignoring case and spaces), or None."""
    key = _serial_key(serial)
    if not key:
        return None
    return next((scope for scope in Scope.objects.all() if _serial_key(scope.serial_number) == key), None)


def _form_date(value):
    return f'{value.month}/{value.day}/{value.year}' if value else ''


def with_library_scope(values):
    """
    Setup values (from an .nde file or a saved setup) with what the inventory knows about their
    instrument, matched by serial number: its names as the report writes them, cal due date,
    module, scanner type and analysis software. The file's own software version is kept (it's
    what recorded the data). Returns (values, scope or None).
    """
    scope = library_scope(values.get('scope_serial'))
    if scope is None:
        return values, None
    library = {
        'scope_platform': scope.name,
        'scope_model': scope.model,
        'scope_manufacturer': scope.manufacturer,
        'scope_serial': scope.serial_number,
        'scope_cal_due': _form_date(scope.calibration_due_date),
        # The reference prints N/A for a module part the instrument doesn't have
        'module_model': scope.module_model or 'N/A',
        'module_serial': scope.module_serial or 'N/A',
        'module_cal_due': _form_date(scope.module_cal_due) or 'N/A',
        'scanner_type': scope.scanner_type,
        'analysis_software': scope.software,
        'analysis_software_version': scope.software_version,
    }
    if not values.get('software_version'):
        library['software_version'] = scope.instrument_software_version
    return {**values, **{k: v for k, v in library.items() if v}}, scope
