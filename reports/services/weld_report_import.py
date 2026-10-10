"""
Guided Creation from an existing weld report: an .xlsx of the weld form (100-UTFORM-010 rev 1.3,
filled by hand or made by this app) read back into a new weld report - the header, testing
instrument, probe and group columns, material information and TCG, calibration times, notes,
technician and reviewer, every results row on the Report page and the Continuation page (welds,
their offsets and indications) and each Indication page's picture on its indication.

read_weld_report() reads the workbook (no Excel: xlsx_reader.py) into plain values, cell by cell
from the same cell map the Excel output writes with (weld_form.py, excel_report.py);
build_report_from_import() makes the report from them.
"""
import io
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction

from equipment.matching import match_probe, match_wedge
from equipment.models import SensitivityBlock

from .. import weld_form
from ..models import Report, ReportGroup, ReportImage, ReportProbe, ResultsRow, ResultsTable
from ..report_types import get_report_type
from .excel_report import ACCEPT_COLUMN, CAL_ROWS, COMMENTS_COLUMN, REJECT_COLUMN, RESULT_COLUMNS
from .xlsx_reader import XlsxError, read_workbook, split_ref

logger = logging.getLogger(__name__)

WELD_TYPE = 'paut_weld'
REPORT_EXTENSIONS = ('.xlsx', '.xlsm')

# Report sheet: header cells (excel_report._header)
HEADER_CELLS = {
    'document_filename': 'X2', 'work_order': 'X5', 'client': 'C7', 'address': 'C8', 'contractor': 'C9',
    'item_description': 'C10', 'exam_code': 'C11', 'acceptance_standard': 'L11', 'procedure': 'U11',
    'procedure_rev': 'Z11', 'location': 'C39', 'notes': 'C53',
    'weld_technician': 'C55', 'weld_technician_cert': 'R55', 'weld_reviewer': 'C57', 'weld_reviewer_cert': 'R57',
}
DATE_CELL = 'X3'
CAL_FIELDS = ('cal_time_initial', 'cal_time_check1', 'cal_time_check2', 'cal_time_out')   # F34-F37
KIND_PREFIXES = (('paut', weld_form.PAUT), ('0deg', weld_form.CONV_LONG), ('0°', weld_form.CONV_LONG),
                 ('sw', weld_form.CONV_SHEAR))
# The Indication page's cells and picture area (excel_report: C57, L57, C60, A12:Z56)
INDICATION_WELD, INDICATION_NUMBER = 'C57', 'L57'
PICTURE_ROWS = (12, 56)
RASTER = ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'tif', 'tiff')

KEYS = [key for key, _ in get_report_type(WELD_TYPE).results_columns]
FLAW_KEYS = KEYS[KEYS.index('circ_start'):KEYS.index('flaw_type') + 1]   # Circ Start ... Type


class WeldReportError(Exception):
    """The file isn't a weld report this can read."""


def _na(text):
    return text.strip().upper() in ('N/A', 'NA', 'N / A')


# ── Reading the workbook ───────────────────────────────────────────────────

def _report_sheet(sheets):
    """The Report page: by name, else the sheet with the form's results heading."""
    if 'Report' in sheets:
        return sheets['Report']
    for sheet in sheets.values():
        if sheet.find(r'^\s*weld id\s*$') and sheet.find(r'testing instrument'):
            return sheet
    return None


def _continuation_sheets(sheets):
    return [s for name, s in sheets.items() if name.lower().startswith('continuation')]


def _indication_sheets(sheets):
    return [s for name, s in sheets.items() if name.lower().startswith('indication')]


def _check_layout(sheet):
    """The weld form's labels where the cell map expects them; WeldReportError if not."""
    expected = {'A7': 'customer', 'E16': 'make', 'J16': 'scan', 'U16': 'block type', 'E34': 'initial'}
    wrong = [ref for ref, label in expected.items() if label not in sheet.text(ref).lower()]
    if len(wrong) > 1:
        raise WeldReportError(
            "This isn't laid out like the weld form (100-UTFORM-010 rev 1.3): its labels aren't where the form "
            f"has them ({', '.join(wrong)}). Older template drafts can't be read.")


def _label(heading):
    """'Probe 1\\n(90°)' -> '90°'; 'Group 4       (0°)' -> '0°'; 'Probe 2' -> ''."""
    match = re.search(r'\(([^)]*)\)', heading or '')
    return match.group(1).strip()[:50] if match else ''


def _kind(key, label, values):
    """The probe kind from its Probe Table key ('PAUT 1: …', '0deg 1: …', 'SW 1: …')."""
    if _na(key) and not any(v and not _na(v) for v in values.values()):
        return weld_form.NOT_USED
    lower = key.strip().lower()
    for prefix, kind in KIND_PREFIXES:
        if lower.startswith(prefix):
            return kind
    if label.strip().startswith('0'):
        return weld_form.CONV_LONG
    return weld_form.PAUT


def _numbers(text):
    return [int(n) for n in re.findall(r'\d+', text or '')]


def _probes(sheet):
    probes = []
    for col in weld_form.PROBE_COLUMNS:
        values = {name: sheet.text(f'{col}{row}') for name, _, row in weld_form.PROBE_ROWS}
        key = sheet.text(f'{col}15')
        label = _label(sheet.text(f'{col}13'))
        kind = _kind(key, label, values)
        na = weld_form.PROBE_NA.get(kind, set())
        probe = {'kind': kind, 'label': label, 'key': key,
                 'groups': [n for row in weld_form.RELEVANT_GROUP_ROWS for n in _numbers(sheet.text(f'{col}{row}'))]}
        probe.update({name: ('' if name in na else value) for name, value in values.items()})
        probes.append(probe)
    # Unused columns at the end (N/A and no heading) aren't kept: the output fills them with N/A
    while probes and probes[-1]['kind'] == weld_form.NOT_USED and not probes[-1]['label']:
        probes.pop()
    return probes


def _groups(sheet, probes):
    groups = []
    for number, col in enumerate(weld_form.GROUP_COLUMNS, start=1):
        values = {name: sheet.text(f'{col}{row}') for name, _, row in weld_form.GROUP_ROWS}
        key = sheet.text(f'{col}15')
        # Its probe: the probe column with the same key, else the one listing this group
        probe = next((i for i, p in enumerate(probes) if key and not _na(key) and p['key'].strip() == key.strip()), None)
        if probe is None:
            probe = next((i for i, p in enumerate(probes) if number in p['groups'] and p['kind'] != weld_form.NOT_USED), None)
        unused = (_na(key) or not key) and all(not v or _na(v) for v in values.values())
        kind = probes[probe]['kind'] if probe is not None else weld_form.PAUT
        na = weld_form.GROUP_NA.get(kind, set())
        group = {'label': _label(sheet.text(f'{col}13')), 'probe': None if unused else probe, 'not_applicable': unused,
                 'missing_probe': key if probe is None and not unused and key and not _na(key) else ''}
        group.update({name: ('' if unused or name in na else value) for name, value in values.items()})
        groups.append(group)
    while groups and groups[-1]['not_applicable'] and not groups[-1]['label']:
        groups.pop()
    return groups


def _materials(sheet):
    values = {'pipe_size': sheet.text(weld_form.PIPE_SIZE_CELL)}
    for _, cal, item, row in weld_form.MATERIAL_ROWS:
        values[cal] = sheet.text(f'W{row}')
        if item:
            values[item] = sheet.text(f'Y{row}')
    for prefix, col in weld_form.ADDITIONAL_BLOCKS:
        for _, name, row in weld_form.ADDITIONAL_ROWS:
            values[f'{prefix}_{name}'] = sheet.text(f'{col}{row}')
    values.update({
        'tcg_block': sheet.text('L34'), 'tcg_ref_block': sheet.text('Q34'),
        'tcg_reflector': sheet.text('L35') or sheet.text('N35') or sheet.text('P35'),
        'tcg_thickness': sheet.text('L36'),   # the 1T distance: the output works out 2T and 3T from it
        'tcg_amplitude': sheet.text('L37') or sheet.text('N37') or sheet.text('P37'),
    })
    return values


def _header(sheet):
    values = {name: sheet.text(ref) for name, ref in HEADER_CELLS.items()}
    for name, _, row in weld_form.INSTRUMENT_ROWS:
        values[name] = sheet.text(f'{"A" if row == 15 else "C"}{row}')
    for name, row in zip(CAL_FIELDS, CAL_ROWS):
        values[name] = sheet.text(f'F{row}')
    when = sheet.get(DATE_CELL)
    values['report_date'] = when.date().isoformat() if isinstance(when, datetime) else _parse_date(sheet.text(DATE_CELL))
    return values


def _parse_date(text):
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%B %d, %Y', '%b %d, %Y'):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return ''


def _verdict(sheet, row):
    """The Accept / Reject columns (S: a check mark P, T: ☓) as the editor's Accept / Reject."""
    accept, reject = sheet.text(f'{ACCEPT_COLUMN}{row}'), sheet.text(f'{REJECT_COLUMN}{row}')
    if accept and not reject:
        return 'Accept' if re.match(r'(?i)^[ap✓✔]', accept) else accept
    if reject and not accept:
        return 'Reject' if re.match(r'(?i)^[rfx☓✗✘]', reject) else reject
    return ''


def _results_rows(sheet):
    """The results rows of a Report or Continuation page, in order, blank rows (between welds) left out."""
    headings = [ref for ref in sheet.find(r'^\s*weld id\s*$') if split_ref(ref)[0] == 'A']
    if not headings:
        return []
    first = split_ref(headings[0])[1] + 1
    ends = [split_ref(ref)[1] for ref in sheet.find(r'^\s*(notes|technician)\s*:?\s*$') if split_ref(ref)[0] == 'A']
    last = min([r for r in ends if r > first] or [first + 40]) - 1
    rows = []
    for row in range(first, last + 1):
        cells = [sheet.text(f'{col}{row}') for col in RESULT_COLUMNS]
        comments = sheet.text(f'{COMMENTS_COLUMN}{row}')
        if not any(cells) and not comments:
            continue   # a blank row (the template's check marks in empty rows don't count)
        rows.append(cells + [_verdict(sheet, row), comments])
    return rows


def _composite(pictures):
    """
    One PNG of the pictures in an Indication page's picture area, placed as they are on the page
    (a single raster picture is kept as it is). Returns (bytes, extension) or (None, None).
    """
    from PIL import Image
    opened = []
    for picture in pictures:
        try:
            image = Image.open(io.BytesIO(picture.data))
            image.load()
        except Exception:   # an EMF / WMF Pillow can't draw, a damaged image
            continue
        opened.append((picture, image))
    if not opened:
        return None, None
    if len(opened) == 1 and opened[0][0].ext in RASTER:
        picture = opened[0][0]
        return picture.data, 'jpg' if picture.ext == 'jpeg' else picture.ext
    left = min(p.left for p, _ in opened)
    top = min(p.top for p, _ in opened)
    right = max(p.left + p.width for p, _ in opened)
    bottom = max(p.top + p.height for p, _ in opened)
    # At the pictures' own resolution (the sharpest one's), at most 3000 px across
    scale = max(image.width / max(p.width, 1) for p, image in opened)
    scale = min(scale, 3000 / max(right - left, 1))
    canvas = Image.new('RGB', (max(1, round((right - left) * scale)), max(1, round((bottom - top) * scale))), 'white')
    for picture, image in opened:
        size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
        image = image.convert('RGBA').resize(size, Image.LANCZOS)
        canvas.paste(image, (round((picture.left - left) * scale), round((picture.top - top) * scale)), image)
    out = io.BytesIO()
    canvas.save(out, 'PNG', optimize=True)
    return out.getvalue(), 'png'


def _indication_pages(sheets):
    """[{'weld', 'number', 'picture': bytes or None, 'ext', 'unreadable'}] from the Indication pages."""
    pages = []
    for sheet in _indication_sheets(sheets):
        area = [p for p in sheet.pictures if PICTURE_ROWS[0] <= p.row <= PICTURE_ROWS[1]]
        weld = sheet.text(INDICATION_WELD)
        numbers = _numbers(sheet.text(INDICATION_NUMBER))
        if not area and not weld:
            continue   # the blank master page
        data, ext = _composite(area) if area else (None, None)
        pages.append({'sheet': sheet.name, 'weld': weld, 'number': numbers[0] if numbers else None,
                      'picture': data, 'ext': ext, 'unreadable': bool(area) and data is None})
    return pages


def read_weld_report(fileobj, filename=''):
    """
    Everything on a weld form workbook as plain values:
    {'filename', 'report': {field: text}, 'probes': [...], 'groups': [...], 'rows': [[cell, ...]],
     'indications': [...], 'notes': [what was left out or needs a look]}. Raises WeldReportError.
    """
    try:
        sheets = read_workbook(fileobj)
    except XlsxError as e:
        raise WeldReportError(str(e)) from e
    sheet = _report_sheet(sheets)
    if sheet is None:
        raise WeldReportError("This workbook has no weld form Report page (a sheet with the form's Weld ID "
                              'results table). Short Form and other reports can\'t be read here.')
    _check_layout(sheet)
    probes = _probes(sheet)
    data = {
        'filename': filename,
        'report': {**_header(sheet), **_materials(sheet)},
        'probes': probes,
        'groups': _groups(sheet, probes),
        'rows': _results_rows(sheet),
        'indications': _indication_pages(sheets),
        'notes': [],
    }
    for continuation in _continuation_sheets(sheets):
        data['rows'] += _results_rows(continuation)
    for number, group in enumerate(data['groups'], start=1):
        if group['missing_probe']:
            data['notes'].append(f"Group {number} is on probe '{group['missing_probe']}', which isn't in the probe "
                                 'columns; pick its probe in Equipment.')
    extra_tcg = [sheet.text(f'Q{row}') for row in (35, 36, 37)]
    if any(extra_tcg):
        data['notes'].append(f"The TCG's 4th point ({' / '.join(t for t in extra_tcg if t)}, cells Q35-Q37) isn't on "
                             "the app's form; it prints the 1T, 2T and 3T points.")
    return data


# ── Building the report ────────────────────────────────────────────────────

def _flaw(cells):
    return any(cells[KEYS.index(k)] for k in FLAW_KEYS)


def _norm_weld(text):
    """'FW-5', 'fw5', 'W5' -> 'W5' (the Indication page and the results may name a weld either way)."""
    return re.sub(r'^F(?=W)', '', re.sub(r'[\s-]+', '', (text or '').upper()))


def _attach_indications(rows, pages):
    """
    {row index: page} - each Indication page's picture on its indication: the n-th indication of its
    weld (Weld Number, Indication Number), else the next indication without a picture, in order.
    """
    flaws, weld, counts = [], '', {}
    for i, cells in enumerate(rows):
        weld = cells[0] or weld
        if _flaw(cells):
            counts[_norm_weld(weld)] = counts.get(_norm_weld(weld), 0) + 1
            flaws.append((i, _norm_weld(weld), counts[_norm_weld(weld)]))
    placed = {}
    leftover = []
    for page in pages:
        if page['picture'] is None:
            continue
        target = next((i for i, w, n in flaws if w == _norm_weld(page['weld']) and n == (page['number'] or 1)
                       and i not in placed), None)
        if target is None:
            leftover.append(page)
        else:
            placed[target] = page
    for page in leftover:
        target = next((i for i, _, _ in flaws if i not in placed), None)
        if target is not None:
            placed[target] = page
    return placed, [p for p in leftover if p not in placed.values()]


def _set_values(obj, values):
    for name, value in values.items():
        if value not in (None, '') and hasattr(obj, name):
            setattr(obj, name, value)


def _sensitivity_block(pipe_size):
    """The library block for the report's NPS / Sch ('6in Sch 40', '6" SCH 40'…), or None."""
    def norm(text):
        return re.sub(r'[\s"″]|in(?:ch)?(?=\s*sch)|sch', '', (text or '').lower())
    wanted = norm(pipe_size)
    if not wanted:
        return None
    return next((b for b in SensitivityBlock.objects.all() if norm(b.pipe_size) == wanted), None)


def _catalogue(probe):
    """The catalogue probe and wedge the column's model names (for the scan plan's drawing)."""
    found = match_probe({'model': probe.model}) if probe.model else None
    catalogue_probe = found.item if found else None
    wedge = match_wedge({'model': probe.wedge_model}, catalogue_probe) if probe.wedge_model else None
    return catalogue_probe, wedge.item if wedge else None


def _scan_plan(report, rows, notes):
    """The report's scan plan from its welds' rows, as the editor's Scan plan button makes it."""
    from ..views.scan_plans import _first_number, _weld_skews, add_weld_to_plan, weld_offsets
    at = {key: KEYS.index(key) for key in ('weld_id', 'cl_offset', 'weld_width', 'probe1_location', 'probe1_thk')}
    for cells in rows:
        thickness = _first_number(cells[at['probe1_thk']])
        offsets = weld_offsets(cells[at['cl_offset']])
        if thickness is None or not offsets:
            continue   # an indication row, or nothing to draw from
        for offset in offsets:
            try:
                ok, message, _ = add_weld_to_plan(report, thickness, _first_number(cells[at['weld_width']]), offset,
                                                  _weld_skews(cells[at['probe1_location']]))
            except Exception as e:   # the plan is a convenience: the report stands without it
                logger.exception('Scan plan from an imported weld report')
                ok, message = False, f'The scan plan could not be made ({e}).'
            report.refresh_from_db(fields=['scan_plan'])
            if not ok:
                notes.append(message)
                return


@transaction.atomic
def build_report_from_import(data, defaults=None, job_folder=''):
    """
    The weld report for read_weld_report()'s values, over a defaults set's values for what the
    file leaves blank. Returns (report, notes).
    """
    from .job_import import _set_report_values
    notes = list(data.get('notes') or [])
    values = dict(data['report'])

    report = Report(report_type=WELD_TYPE, report_date=date.today())
    if defaults is not None:
        _set_report_values(report, defaults.report_values)
    when = values.pop('report_date', '')
    if when:
        report.report_date = date.fromisoformat(when)
    _set_values(report, values)
    if not report.document_filename:
        report.document_filename = (Path(job_folder).name if job_folder else Path(data.get('filename') or '').stem)[:200]
    report.job_folder = str(job_folder or '')
    report.sensitivity_block = _sensitivity_block(values.get('pipe_size'))
    report.save()

    probe_fields = {name for name, _, _ in weld_form.PROBE_ROWS}
    saved = []
    for order, values in enumerate(data['probes']):
        probe = ReportProbe(report=report, order=order, kind=values['kind'], label=values['label'])
        _set_values(probe, {k: v for k, v in values.items() if k in probe_fields})
        if probe.kind != weld_form.NOT_USED:
            probe.catalogue_probe, probe.catalogue_wedge = _catalogue(probe)
        probe.save()
        saved.append(probe)
    group_fields = {name for name, _, _ in weld_form.GROUP_ROWS}
    for order, values in enumerate(data['groups']):
        group = ReportGroup(report=report, order=order, label=values['label'], not_applicable=values['not_applicable'])
        _set_values(group, {k: v for k, v in values.items() if k in group_fields})
        index = values.get('probe')
        group.probe = saved[index] if index is not None and index < len(saved) else None
        group.save()
    if len(data['probes']) > weld_form.MAX_PROBES or len(data['groups']) > weld_form.MAX_GROUPS:
        notes.append('The file has more probe or group columns than the form holds.')

    # The results: every row, an indication's row keyed for its picture (the cell after Notes)
    rows = [list(cells) + [''] * (len(KEYS) - len(cells)) for cells in data['rows']]
    pages = data.get('indications') or []
    placed, unplaced = _attach_indications(rows, pages)
    table = ResultsTable.objects.create(report=report, columns=get_report_type(WELD_TYPE).results_headings)
    image_order = 0
    for order, cells in enumerate(rows):
        cells = cells[:len(KEYS)]
        if _flaw(cells):
            key = f'ind-imp{report.pk}r{order}'
            cells.append(key)
            page = placed.get(order)
            if page is not None:
                image = ReportImage(report=report, kind=ReportImage.INDICATION, scan_id=key, order=image_order)
                image.image.save(f'imported_{report.pk}_{order}.{page["ext"]}', ContentFile(page['picture']), save=False)
                image.save()
                image_order += 1
        ResultsRow.objects.create(table=table, cells=cells, order=order)

    unreadable = [p['sheet'] for p in pages if p['unreadable']]
    if unreadable:
        notes.append(f"The picture on {', '.join(unreadable)} couldn't be read (a drawing format this can't open); "
                     'add it again in Results.')
    if unplaced:
        notes.append(f"{len(unplaced)} Indication page picture(s) had no indication row to go with "
                     f"({', '.join(p['sheet'] for p in unplaced)}).")
    _scan_plan(report, rows, notes)
    return report, notes


def import_weld_report(fileobj, filename='', defaults=None, job_folder=''):
    """read_weld_report() then build_report_from_import(): (report, notes, data)."""
    data = read_weld_report(fileobj, filename)
    report, notes = build_report_from_import(data, defaults, job_folder)
    return report, notes, data


def folder_reports(folder):
    """The weld reports (.xlsx) in a job folder, newest first (Excel's ~$ lock files left out)."""
    try:
        entries = [e for e in os.scandir(folder) if e.is_file() and e.name.lower().endswith(REPORT_EXTENSIONS)
                   and not e.name.startswith('~$')]
    except OSError:
        return []
    return [Path(e.path) for e in sorted(entries, key=lambda e: -e.stat().st_mtime)]
