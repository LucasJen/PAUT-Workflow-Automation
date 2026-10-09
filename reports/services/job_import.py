"""
"New weld report from files": a job's .nde files read in one go and made into a weld report.

read_job_file() reads one file into JSON-able data (its probe / group columns as the grid's
Import .nde gives them, the part, scan time, C/L offset and a guessed weld ID); build_report()
then makes the report from all the files and a defaults set: the instrument, probe and group
columns placed as the grid places imports (place_columns), the sensitivity block found for the
part, a weld row per weld, the calibration window from the scan times and the scan plan.
"""
import re
from datetime import date, datetime, timedelta

from django.db import transaction

from equipment.importers import probe_from_nde, wedge_from_nde
from equipment.inventory import with_library_scope
from equipment.matching import match_probe, match_wedge

from .. import weld_form
from ..materials import block_values, part_values
from ..models import Report, ReportGroup, ReportProbe, ResultsRow, ResultsTable
from ..report_types import get_report_type
from ..weld_columns import columns_from_setup, probe_key
from .nde_parser import NdeError, extract_groups, read_nde

WELD_TYPE = 'paut_weld'
# 'PPI 31-37575 w5 n off1' -> W5, 'FHR 14-44929 W11 BOT' -> W11, 'FW-12' -> FW12
WELD_NAME = re.compile(r'(?<![a-z0-9])(f?w)\s*-?\s*(\d+[a-z]?)(?![0-9])', re.I)
NUMBER = re.compile(r'-?\d+(?:\.\d+)?')


def _number(text):
    match = NUMBER.search(str(text or ''))
    return float(match.group()) if match else None


# ── One file ──────────────────────────────────────────────────────────────

def scope_label(scope):
    """'Omniscan X3 QC-0030383' for a scope found in the library, else ''."""
    return f'{scope.name or scope.model} {scope.serial_number}'.strip() if scope else ''


def catalogue_match(hardware):
    """
    The catalogue probe and wedge for a group's hardware: ({setup field: value} to fill in, and a
    summary for the NDE page with what matched, how, geometry differences, and the file's own
    values for 'Add to catalogue' when nothing matched).
    """
    file_probe = probe_from_nde(hardware['probe']) if hardware.get('probe') else {}
    file_wedge = wedge_from_nde(hardware['wedge'], hardware.get('mounting_id')) if hardware.get('wedge') else {}
    probe = match_probe(file_probe) if file_probe else None
    wedge = match_wedge(file_wedge, probe.item if probe else None) if file_wedge else None

    def summary(match, file_fields):
        if not file_fields:
            return None
        if match is None or match.item is None:
            return {'file_name': file_fields.get('model', ''), 'file_fields': file_fields}
        info = {'file_name': file_fields.get('model', ''), 'pk': match.item.pk, 'name': str(match.item),
                'how': match.how, 'differences': match.differences}
        suggestion = getattr(match, 'suggestion', None)
        if suggestion is not None:
            info['suggestion'] = {'pk': suggestion.pk, 'name': str(suggestion)}
        return info

    fill = {
        'catalogue_probe': probe.item.pk if probe and probe.item else '',
        'catalogue_wedge': wedge.item.pk if wedge and wedge.item else '',
        'first_element': hardware.get('first_element') or '',
        'aperture_elements': hardware.get('aperture') or '',
    }
    return fill, {'probe': summary(probe, file_probe), 'wedge': summary(wedge, file_wedge)}


def file_items(setup, properties, filename, system):
    """
    The grid's import items for each inspection group of a file: {instrument, probe, group,
    probe_key, probe_ref, part, scan_time, scope, label, title, filename}.
    """
    items = []
    for group in extract_groups(setup, properties, filename):
        hardware = group.get('hardware', {})
        fill, _ = catalogue_match(hardware)
        values, scope = with_library_scope({**group['values'][system], **fill})
        item = columns_from_setup(values)
        item['scope'] = scope_label(scope)
        name = group['label'].split(' · ')[0]
        # A group column remembers the file and group it came from (importing again updates it);
        # groups on the same probe of the file share its probe column
        item['group']['source_file'] = f'{filename} › {name}'[:255]
        probe_id = (hardware.get('probe') or {}).get('id')
        items.append({**item, 'label': name, 'title': group['label'], 'filename': filename,
                      'probe_ref': f'{filename}#{probe_id}' if probe_id is not None else '',
                      'index_offset': values.get('index_offset'), 'thickness': values.get('specimen_thickness')})
    return items


def guess_weld(filename):
    """The weld a file name names, e.g. 'PPI 31-37575 w5 n off1.nde' -> 'W5'; '' when none."""
    match = WELD_NAME.search(filename.rsplit('.', 1)[0])
    return f'{match.group(1).upper()}{match.group(2).upper()}' if match else ''


def read_job_file(uploaded, system='imperial'):
    """One .nde of the job as JSON-able data, or {'filename', 'error'}."""
    try:
        setup, properties = read_nde(uploaded)
    except NdeError as e:
        return {'filename': uploaded.name, 'error': str(e)}
    items = file_items(setup, properties, uploaded.name, system)
    if not items:
        return {'filename': uploaded.name, 'error': 'No inspection groups in this file.'}
    first = items[0]
    return {
        'filename': uploaded.name,
        'weld': guess_weld(uploaded.name),
        'scan_time': first.get('scan_time', ''),
        'offset': _number(first.get('index_offset')),
        'thickness': _number(first.get('thickness')),
        'groups': [item['title'] for item in items],
        'items': items,
    }


# ── Placing the files' probes and groups in the columns ─────────────────────

def place_columns(probes, groups, items):
    """
    The grid's import rules (weld_grid.js importColumns) on column dicts: each item's probe goes
    to the column of the same probe in its file, else the same model and S/N, else the first
    column of its kind no file has filled (e.g. a defaults column), else a new one; its group to
    the column from the same file and group, else one waiting on that probe or kind, else a new
    one. A group with the same settings on the same probe as one already there (the same setup
    scanned on another weld or side) shares it. The file's values replace what's there; values
    it doesn't have (and labels) stay.
    Returns (probes, groups, skipped). Groups' probe_column is the probe's index ('na' = N/A).
    """
    probes = [dict(p) for p in probes]
    groups = [dict(g) for g in groups]
    placed, claimed, skipped = {}, set(), 0

    def fillable(column):
        return not column.get('source_file')

    def fill(column, values):
        for name, value in values.items():
            if name == 'label' and column.get('label'):
                continue
            if value not in (None, ''):
                column[name] = value

    for item in items:
        kind = item['probe'].get('kind') or weld_form.PAUT
        index = placed.get(item.get('probe_ref')) if item.get('probe_ref') else None
        if index is None and item.get('probe_key'):
            index = next((i for i, p in enumerate(probes) if probe_key(p) == item['probe_key']), None)
        if index is None:
            index = next((i for i, p in enumerate(probes) if fillable(p) and (p.get('kind') or weld_form.PAUT) == kind), None)
        if index is None:
            if len(probes) >= weld_form.MAX_PROBES:
                skipped += 1
                continue
            probes.append({'kind': kind})
            index = len(probes) - 1
        if index not in placed.values():
            fill(probes[index], item['probe'])
        if item.get('probe_ref'):
            placed[item['probe_ref']] = index

        def probe_kind(group):
            column = group.get('probe_column', '')
            if column == weld_form.NOT_USED:
                return weld_form.NOT_USED
            return probes[int(column)].get('kind', weld_form.PAUT) if str(column).isdigit() and int(column) < len(probes) else None

        # A group with the same settings on the same probe (the same setup scanned on another
        # weld or side) is the same group on the form
        settings = {k: v for k, v in item['group'].items() if k != 'source_file' and v not in (None, '')}
        same = next((i for i, g in enumerate(groups) if str(g.get('probe_column', '')) == str(index)
                     and settings and all(str(g.get(k, '')) == str(v) for k, v in settings.items())), None)
        if same is not None:
            claimed.add(same)
            continue
        source = item['group'].get('source_file')
        open_groups = [i for i in range(len(groups)) if i not in claimed]
        target = next((i for i in open_groups if source and groups[i].get('source_file') == source), None)
        if target is None:
            waiting = [i for i in open_groups if fillable(groups[i])]
            target = next((i for i in waiting if str(groups[i].get('probe_column', '')) == str(index)), None)
            if target is None:
                target = next((i for i in waiting if probe_kind(groups[i]) == kind), None)
        if target is None:
            if len(groups) >= weld_form.MAX_GROUPS:
                skipped += 1
                continue
            groups.append({})
            target = len(groups) - 1
        claimed.add(target)
        fill(groups[target], item['group'])
        groups[target]['probe_column'] = str(index)
    return probes, groups, skipped


# ── The report ───────────────────────────────────────────────────────────

def _scan_moments(scan_times):
    """The files' scan times ('2026-09-28 08:09') as datetimes; a time without a date counts as one day."""
    moments = []
    for text in scan_times:
        match = re.search(r'(?:(\d{4})-(\d{2})-(\d{2})[T ])?(\d{2}):(\d{2})', text or '')
        if match:
            y, mo, d, h, mi = match.groups()
            day = date(int(y), int(mo), int(d)) if y else date(2000, 1, 1)
            moments.append(datetime(day.year, day.month, day.day, int(h), int(mi)))
    return moments


def calibration_window(scan_times):
    """
    ('HHMM' initial, 'HHMM' out): 15 min before the earliest scan (down to 5 min), 15 after the
    latest (up), by date and time, so scans over midnight or several days get the first scan's
    and the last scan's times.
    """
    moments = _scan_moments(scan_times)
    if not moments:
        return '', ''
    start = min(moments) - timedelta(minutes=15)
    start -= timedelta(minutes=start.minute % 5)
    end = max(moments) + timedelta(minutes=15)
    end += timedelta(minutes=-end.minute % 5)
    return start.strftime('%H%M'), end.strftime('%H%M')


def scan_days(scan_times):
    """The days the files were scanned on, first to last ([] when they don't say)."""
    return sorted({m.date() for m in _scan_moments(scan_times) if m.year != 2000})


def welds_from_files(files):
    """
    {weld ID: {'offsets': [...], 'thickness', 'files', 'location', 'locations'}} in the order the
    welds first appear, from the files' (confirmed) weld IDs. A weld scanned from both sides (two
    or more files at one offset) is '90/270'; 'locations' is that per offset, in offset order.
    """
    welds = {}
    for data in files:
        weld = welds.setdefault(data['weld'], {'offsets': [], 'thickness': None, 'files': [], 'per_offset': {}})
        weld['files'].append(data['filename'])
        if data.get('offset') is not None and data['offset'] not in weld['offsets']:
            weld['offsets'].append(data['offset'])
        weld['per_offset'][data.get('offset')] = weld['per_offset'].get(data.get('offset'), 0) + 1
        weld['thickness'] = weld['thickness'] or data.get('thickness')
    for weld in welds.values():
        weld['location'] = '90/270' if len(weld['files']) > len(weld['offsets'] or [None]) else '90'
        per_offset = weld.pop('per_offset')
        weld['locations'] = ['90/270' if per_offset.get(offset, 0) > 1 else '90' for offset in weld['offsets']]
    return welds


def _set_report_values(report, values):
    """Report field values as stored in a defaults set (foreign keys as their pk)."""
    for name, value in values.items():
        field = next((f for f in Report._meta.concrete_fields if f.name == name), None)
        if field is None or value in (None, ''):
            continue
        setattr(report, field.attname, value)


def job_part(files):
    """The part the files' groups recorded (OD, wall, material…), merged."""
    part = {}
    for item in (item for data in files if not data.get('error') for item in data['items']):
        part.update(item.get('part') or {})
    return part


@transaction.atomic
def build_report(files, defaults=None, document_filename='', block=None, job_folder='', client=None):
    """
    The weld report for these read files (read_job_file, with confirmed 'weld' IDs; files with an
    'error' are left out) starting from a defaults set, with the sensitivity block picked for the
    job (none: the card is left to fill in). `job_folder` is where its downloads are saved;
    `client` a ClientCode, over the defaults' client and location. Returns (report, notes).
    """
    from ..views.scan_plans import add_weld_to_plan
    files = [f for f in files if not f.get('error')]
    items = [item for data in files for item in data['items']]
    notes = []

    report = Report(report_type=WELD_TYPE, report_date=date.today())   # as a new report in the editor
    if defaults is not None:
        _set_report_values(report, defaults.report_values)
    report.document_filename = document_filename or report.document_filename
    report.job_folder = str(job_folder or '')
    if client is not None:
        report.client = client.client
        report.location = client.location or report.location
    # The instrument: the files' (with the scope library's details)
    for name, value in (items[0]['instrument'] if items else {}).items():
        setattr(report, name, value)
    scan_times = [d.get('scan_time') for d in files]
    report.cal_time_initial, report.cal_time_out = calibration_window(scan_times)
    days = scan_days(scan_times)
    if len(days) > 1:
        notes.append(f'The files were scanned over {len(days)} days ({days[0]:%b %d} to {days[-1]:%b %d}): the '
                     f'calibration times run from the first scan ({report.cal_time_initial}) to the last '
                     f"({report.cal_time_out}). Check them against each day's calibration.")

    # The part and its sensitivity block
    part = job_part(files)
    report.scan_part = part or None
    if block is not None:
        for name, value in {**block_values(block), **part_values(part, block)}.items():
            setattr(report, 'sensitivity_block_id' if name == 'sensitivity_block' else name, value)
    report.save()

    # Probe and group columns: the defaults' prefilled ones, filled from the files
    probes, groups, skipped = place_columns(
        defaults.probe_columns if defaults else [], defaults.group_columns if defaults else [], items)
    if skipped:
        notes.append(f'{skipped} group(s) left out: the form holds {weld_form.MAX_PROBES} probes and '
                     f'{weld_form.MAX_GROUPS} groups.')
    probe_fields = {f.attname for f in ReportProbe._meta.concrete_fields} - {'id', 'report_id', 'order'}
    saved = []
    for order, values in enumerate(probes):
        probe = ReportProbe(report=report, order=order)
        for name, value in values.items():
            if name in ('catalogue_probe', 'catalogue_wedge'):
                setattr(probe, f'{name}_id', int(value) if str(value).isdigit() else None)
            elif name in probe_fields:
                setattr(probe, name, value)
        diameter = weld_form.wedge_diameter_for(probe.kind, report.item_diameter)   # the pipe's
        if diameter is not None:
            probe.wedge_diameter = diameter
        probe.save()
        saved.append(probe)
    group_fields = {f.attname for f in ReportGroup._meta.concrete_fields}
    for order, values in enumerate(groups):
        group = ReportGroup(report=report, order=order)
        for name, value in values.items():
            if name in group_fields and name not in ('id', 'report_id', 'order', 'probe_id'):
                setattr(group, name, value)
        column = str(values.get('probe_column', ''))
        group.not_applicable = column == weld_form.NOT_USED
        group.probe = saved[int(column)] if column.isdigit() and int(column) < len(saved) else None
        group.save()

    # A weld row each, then the scan plan from them
    welds = welds_from_files(files)
    headings = get_report_type(WELD_TYPE).results_headings
    table = ResultsTable.objects.create(report=report, columns=headings)
    keys = [key for key, _ in get_report_type(WELD_TYPE).results_columns]
    order = 0
    for weld_id, weld in welds.items():
        # A row per offset the weld's files were scanned at: the first with the Weld ID, each
        # further one the weld's next row (as the editor's offset rows)
        thickness = f"{weld['thickness']:.3f}" if weld['thickness'] is not None else ''
        parts = list(zip(weld['offsets'], weld['locations'])) or [(None, weld['location'])]
        for n, (offset, location) in enumerate(parts):
            cells = {'weld_id': weld_id if not n else '', 'cl_offset': f'{offset:.3f}' if offset is not None else '',
                     'probe1_location': location, 'probe1_thk': thickness}
            ResultsRow.objects.create(table=table, cells=[cells.get(key, '') for key in keys], order=order)
            order += 1
            skews = {90, 270} if location == '90/270' else {90}
            ok, message, _ = add_weld_to_plan(report, weld['thickness'], None, offset, skews)
            if not ok:
                notes.append(f'{weld_id}: {message}')
    return report, notes
