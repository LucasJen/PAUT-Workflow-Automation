"""
OmniPC's exports turned into readings points for layer L1, so each export is dozens of checks with
nothing retyped. OmniPC's Export (indications.csv, with setup.csv beside it in the zip) lists each
indication's scan / index position, angle or VPA, and the reading columns chosen in OmniPC, as text
cells like ="12.940 in". Positions are turned into the file's cells from its own axes, read by the
independent reference reader.

A points file (kit points/*.json, role 'readings'; also 'sizing' when the cursors were put on the -6 dB
ends, 'detection' when the export lists every indication in the file):
    {"file": "nde/x.nde", "group": 0, "units": "in", "source": "...", "detection": {"A": "maxpeak"},
     "sizing": "6" | null, "complete": true | false,
     "points": [{"number": 1, "scan": 329, "beam": 21, "expected": {"A%": 44.008, "SA^": 1.047},
                 "decimals": {"A%": 3, "SA^": 3}, "cursors": {"S(r)": 12.1, "S(m)": 13.4},
                 "not_compared": {"S(m-r)": "needs the cursor positions"}}]}
"""
import csv
import io
import json
import os
import re
import zipfile

from . import reference

INCH, MM = 0.0254, 0.001
_CELL = re.compile(r'^="?(.*?)"?$')
_NUMBER = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*(.*?)\s*$')
FIXED = {'#', 'Group', 'Scan', 'Index', 'Angle', 'VPA', 'Reference', 'Type', 'Status', 'Comment'}
# Readings that need more than the cursor's A-scan: the cursors' positions or a zone
NEEDS = {'S(m-r)': 'the reference and measure cursor positions', 'U(m-r)': 'the reference and measure cursor positions',
         'I(m-r)': 'the reference and measure cursor positions',
         'TminZ': 'the zone it was taken over', 'S(TminZ)': 'the zone it was taken over', 'I(TminZ)': 'the zone it was taken over'}
# The cursors' own positions: kept with the point (L2 sizes against them when they were put on the dB-drop ends)
CURSORS = ('S(r)', 'S(m)', 'U(r)', 'U(m)', 'I(r)', 'I(m)')
PEAK_SELECTION = {'highest': 'maxpeak', 'first': 'peak', 'last': 'maxpeak'}


class ImportError_(Exception):
    """The export can't be turned into points."""


def cell(text):
    """('12.940', 'in') from ="12.940 in"; (None, '') for '-' or empty."""
    text = (text or '').strip()
    match = _CELL.match(text)
    inner = (match.group(1) if match else text).strip()
    if inner in ('', '-'):
        return None, ''
    number = _NUMBER.match(inner)
    return (number.group(1), number.group(2)) if number else (None, inner)


def _decimals(number):
    return len(number.split('.')[1]) if '.' in number else 0


def parse_indications(text):
    """Rows of indications.csv: [{number, group, scan, index, angle, vpa, readings: {name: (text number, unit)}}]."""
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    header = [h.strip() for h in next(reader, [])]
    if '#' not in header or 'Scan' not in header:
        raise ImportError_("This isn't an OmniPC indications.csv (no # / Scan columns).")
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        row = dict(zip(header, values))
        rows.append({
            'number': int(row['#']) if row.get('#', '').strip().isdigit() else len(rows) + 1,
            'group': row.get('Group', '').strip(),
            'scan': cell(row.get('Scan')), 'index': cell(row.get('Index')),
            'angle': cell(row.get('Angle')), 'vpa': cell(row.get('VPA')),
            'readings': {name: cell(row[name]) for name in header if name not in FIXED and name in row},
        })
    return rows


def parse_setup(text):
    """From setup.csv: each gate's peak selection, {'A': 'maxpeak', ...} (OmniPC's ^ readings read there)."""
    detection = {}
    lines = list(csv.reader(io.StringIO(text.lstrip('﻿'))))
    for n, line in enumerate(lines):
        cells = [c.strip() for c in line]
        if 'Gates' in cells and 'Peak Selection' in cells:
            first = cells.index('Gates')
            column = cells.index('Peak Selection') - first
            for gate_line in lines[n + 1:]:
                g = [c.strip() for c in gate_line]
                if not g or len(g) <= column or not re.fullmatch(r'[A-Z]', g[0] or ''):
                    break
                detection[g[0]] = PEAK_SELECTION.get(g[column].lower(), 'maxpeak')
    return detection


def parse_setup_values(text):
    """
    setup.csv's values: {'values': {name: cell text}, 'gates': [{name, start, width, threshold, synchro}]}
    (name / value pairs along each line; the gate table under its Gates / Start / Width header).
    """
    lines = list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))
    values, gates = {}, []
    for n, line in enumerate(lines):
        cells = [c.strip() for c in line]
        if 'Gates' in cells and 'Start' in cells:
            first = cells.index('Gates')
            columns = {name.lower(): k - first for k, name in enumerate(cells[first:], first) if name}
            for gate_line in lines[n + 1:]:
                g = [c.strip() for c in gate_line]
                if not g or not re.fullmatch(r'[A-Z]', g[0] or ''):
                    break
                cell = lambda key: g[columns[key]] if key in columns and columns[key] < len(g) else ''
                gates.append({'name': g[0], 'start': cell('start'), 'width': cell('width'),
                              'threshold': cell('threshold'), 'synchro': cell('synchro')})
            cells = cells[:first]
        for k in range(0, len(cells) - 1, 2):
            if cells[k] and cells[k + 1] and cells[k] not in values:
                values[cells[k]] = cells[k + 1]
    return {'values': values, 'gates': gates}


def read_setup(path):
    """setup.csv's text from an export zip (or the CSV itself), or ''."""
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if os.path.basename(n).lower() == 'setup.csv'), None)
            return z.read(name).decode('utf-8-sig') if name else ''
    with open(path, encoding='utf-8-sig') as f:
        return f.read()


def import_setup(kit, export_path, nde_entry, source='', copy=True):
    """Adds an OmniPC export's setup.csv (the zip as received) and a setup file made from it (role 'setup')."""
    text = read_setup(export_path)
    if not text:
        raise ImportError_('The export has no setup.csv.')
    setup = parse_setup_values(text)
    export_entry = kit.add(export_path, ['setup'], source or 'OmniPC export', 'As exported from OmniPC.', copy=copy)
    stem = os.path.splitext(os.path.basename(export_entry['path']))[0]
    target = os.path.join(kit.root, 'points', f'{stem} setup.json')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump({'file': nde_entry['path'], 'export': export_entry['path'], 'source': source, 'setup': setup}, f, indent=2)
    return kit.add(target, ['setup'], f"Made from {export_entry['path']}", f"{len(setup['values'])} values, {len(setup['gates'])} gates")


def read_export(path):
    """(indications.csv text, setup.csv text or '') from an OmniPC export zip, or a CSV on its own."""
    if path.lower().endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            names = {os.path.basename(n).lower(): n for n in z.namelist()}
            if 'indications.csv' not in names:
                raise ImportError_('The zip has no indications.csv.')
            setup = z.read(names['setup.csv']).decode('utf-8-sig') if 'setup.csv' in names else ''
            return z.read(names['indications.csv']).decode('utf-8-sig'), setup
    with open(path, encoding='utf-8-sig') as f:
        text = f.read()
    setup_path = os.path.join(os.path.dirname(path), 'setup.csv')
    setup = open(setup_path, encoding='utf-8-sig').read() if os.path.isfile(setup_path) else ''
    return text, setup


def _metres(value, unit):
    return float(value) * (INCH if unit == 'in' else MM)


def to_points(rows, nde_path, kit_file, source='', detection=None, sizing=None, complete=False):
    """
    {group id: points file dict} for the rows, their positions turned into cells with the file's axes.
    A row whose position can't be placed is kept with a 'problem' instead of a cell, so it shows.
    """
    groups = [g for g in reference.groups(nde_path) if g['amplitude']]
    out = {}
    for row in rows:
        group = next((g for g in groups if g['name'] == row['group']), None) or (groups[0] if len(groups) == 1 else None)
        if group is None:
            continue
        dims = reference.dims(group)
        units = next((u for _, u in (row['scan'], row['index']) if u in ('in', 'mm')), 'in')
        spec = out.setdefault(group['id'], {'file': kit_file, 'group': group['id'], 'units': units, 'source': source,
                                            'detection': detection or {}, 'sizing': sizing, 'complete': complete, 'points': []})
        point = {'number': row['number'], 'expected': {}, 'decimals': {}, 'cursors': {}, 'not_compared': {}}
        scan_value, scan_unit = row['scan']
        u = dims[0]
        if scan_value is None:
            point['problem'] = 'No scan position in the export.'
        else:
            point['scan_position'] = float(scan_value)
            point['scan'] = round((_metres(scan_value, scan_unit) - (u.get('offset') or 0.0)) / u['resolution'])
        if len(dims) == 3 and dims[1].get('axis') == 'VCoordinate':
            index_value, index_unit = row['index']
            v = dims[1]
            if index_value is None:
                point['problem'] = 'No index position in the export.'
            else:
                point['index_position'] = float(index_value)
                point['index'] = round((_metres(index_value, index_unit) - (v.get('offset') or 0.0)) / v['resolution'])
        elif len(dims) == 3:
            beams = dims[1].get('beams') or []
            angle, _ = row['angle']
            if angle is not None and beams:
                nearest = min(range(len(beams)), key=lambda k: abs(beams[k].get('refractedAngle', 0.0) - float(angle)))
                if abs(beams[nearest].get('refractedAngle', 0.0) - float(angle)) <= 0.05:
                    point['beam'], point['angle'] = nearest, float(angle)
                else:
                    point['problem'] = f'No beam at {angle} deg in the file.'
            else:
                point['problem'] = 'The beam is given by VPA, which is not placed yet - export the Angle column.'
        else:
            point['beam'] = 0   # one line
        for name, (value, unit) in row['readings'].items():
            if value is None:
                continue
            if name in CURSORS:
                point['cursors'][name] = float(value)
                continue
            if name in NEEDS:
                point['not_compared'][name] = f'needs {NEEDS[name]}, which the export does not include'
                continue
            point['expected'][name] = float(value)
            point['decimals'][name] = _decimals(value)
        spec['points'].append(point)
    return out


def import_export(kit, export_path, nde_entry, source='', sizing=None, complete=False):
    """
    Adds an OmniPC export to the kit: the export itself (role 'readings', as received) and a points
    file per group made from it (role 'readings', plus 'sizing' when its cursors were put on the
    `sizing` dB-drop ends, plus 'detection' when it lists every indication in the file). Returns the
    points entries.
    """
    text, setup = read_export(export_path)
    rows = parse_indications(text)
    if not rows:
        raise ImportError_('The export has no indications.')
    stem = os.path.splitext(os.path.basename(nde_entry['path']))[0]
    name = os.path.basename(export_path)
    if name.lower() in ('indications.csv', 'export.zip'):   # OmniPC's own names: say which file it's from
        name = f'{stem} - {name}'
    export_entry = kit.add(export_path, ['readings'], source or 'OmniPC export', 'As exported from OmniPC.', name=name)
    specs = to_points(rows, kit.full_path(nde_entry), nde_entry['path'], source or export_entry['path'], parse_setup(setup) if setup else {},
                      sizing=sizing, complete=complete)
    entries = []
    for gid, spec in specs.items():
        spec['export'] = export_entry['path']
        name = f"{os.path.splitext(os.path.basename(export_entry['path']))[0]} G{gid}.json"
        target = os.path.join(kit.root, 'points', name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(spec, f, indent=2)
        roles = ['readings'] + (['sizing'] if sizing else []) + (['detection'] if complete else [])
        entries.append(kit.add(target, roles, f"Made from {export_entry['path']}", f"{len(spec['points'])} indications"))
    return entries
