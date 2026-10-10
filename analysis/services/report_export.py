"""
Send saved indications into a report's results table - one function for every report type.

Every report type keeps its results as a ResultsTable (column headings) with ResultsRows (cells),
and its pictures as ReportImages tied to a row. An indication becomes one row: each column is
filled from what the indication measured, picked by the report type's column key when the column
is one of the type's own (reports/report_types.py), else by its heading's words, so columns a user
renamed or added fill too. Columns nothing fits are left blank for the user. Lengths go out in the
column's own units when its heading says (in / mm), else the units asked for.

The weld form ties an indication's picture to a key kept as one extra cell after the row (as the
weld results editor does); the other forms tie a scan picture to the row's Scan ID.
"""
import base64
import binascii
import os
import re
import secrets

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from reports.models import Report, ReportImage, ResultsRow, ResultsTable
from reports.report_types import get_report_type

WELD_TYPE = 'paut_weld'

# What an indication can fill (field -> description, for the preview's hints)
FIELDS = {
    'scan_id': 'File and indication number',
    'scan_start': 'Scan start (reference cursor, else the scan line)',
    'scan_stop': 'Scan stop (measure cursor)',
    'scan_range': 'Scan start / stop',
    'index_pos': 'Index position of the peak',
    'index_range': 'Index start / stop',
    'length': 'Length from the sizing (or between the scan cursors)',
    'depth': 'Depth of the gate A peak',
    'height': 'Height between the depth cursors',
    'amplitude': 'Peak amplitude, % of full screen',
    'thickness_min': 'Least thickness (zone Tmin, else the thickness reading)',
    'thickness_avg': 'Average thickness in the zone',
    'angle': 'Beam angle',
    'comment': 'The indication comment',
}

# The report types' own column keys -> field
KEY_FIELDS = {
    'scan_id': 'scan_id', 'circ_start': 'scan_start', 'length': 'length', 'axial_pos': 'index_pos',
    'depth': 'depth', 'height': 'height', 'amp': 'amplitude', 'comments': 'comment',
    'min_thk': 'thickness_min', 'avg_thk': 'thickness_avg',
    'x_range': 'scan_range', 'circ': 'scan_range', 'y_range': 'index_range', 'axial': 'index_range',
}

# Any other heading, by its words (first match wins)
HEADING_FIELDS = [
    (r'\bscan\s*id\b|\bfile\b|\bid\b', 'scan_id'),
    (r'\bmin', 'thickness_min'),
    (r'\bavg\b|\baverage\b|\bmean\b', 'thickness_avg'),
    (r'\bthk\b|\bthick', 'thickness_min'),
    (r'\blength\b|\blen\b', 'length'),
    (r'\bheight\b|through[- ]?wall', 'height'),
    (r'\bdepth\b', 'depth'),
    (r'\bamp|\bamplitude\b|%', 'amplitude'),
    (r'\bangle\b', 'angle'),
    (r'start\s*/\s*stop|\brange\b', 'scan_range'),
    (r'\bstart\b|\bscan\b|\bcirc', 'scan_start'),
    (r'\bstop\b|\bend\b', 'scan_stop'),
    (r'\bindex\b|\baxial\b|\bposition\b|\bpos\b', 'index_pos'),
    (r'\bcomment|\bnote|\bresult|\bremark|\bdescription\b', 'comment'),
]

LENGTH_FIELDS = {'scan_start', 'scan_stop', 'scan_range', 'index_pos', 'index_range', 'length', 'depth',
                 'height', 'thickness_min', 'thickness_avg'}


class ExportError(Exception):
    """Something the user should be told (an issued report, a bad request)."""


def _norm(text):
    return re.sub(r'[^a-z0-9%]+', ' ', (text or '').lower()).strip()


def field_for(heading, type_columns):
    """The indication field a column takes: by the report type's key for its own headings, else by words."""
    by_heading = {_norm(h): k for k, h in type_columns}
    key = by_heading.get(_norm(heading))
    if key is not None:
        return KEY_FIELDS.get(key)
    text = _norm(heading)
    for pattern, field in HEADING_FIELDS:
        if re.search(pattern, text):
            return field
    return None


def units_for(heading, default):
    """'in' or 'mm' from a heading like 'Depth (in)' / 'Min. Thickness (in.)' / 'Length mm', else the default."""
    text = (heading or '').lower()
    if re.search(r'\bmm\b', text):
        return 'mm'
    if re.search(r'\(in\.?\)|\binch|\bin\.?$', text):
        return 'in'
    return default


def _length(metres, units):
    if metres is None:
        return ''
    return f'{metres * 1000:.1f}' if units == 'mm' else f'{metres / 0.0254:.3f}'


def indication_values(indication, units='in', numbered=True):
    """Every field an indication can fill, formatted (lengths in `units`)."""
    r = indication.readings or {}
    c = indication.cursors or {}
    has = lambda v: isinstance(v, (int, float))
    s_ref, s_meas = c.get('s_ref'), c.get('s_meas')
    i_ref, i_meas = c.get('i_ref'), c.get('i_meas')
    u_ref, u_meas = c.get('u_ref'), c.get('u_meas')
    both_s, both_i = has(s_ref) and has(s_meas), has(i_ref) and has(i_meas)
    scan_start = min(s_ref, s_meas) if both_s else (s_ref if has(s_ref) else indication.scan_position)
    scan_stop = max(s_ref, s_meas) if both_s else None
    index_pos = r.get('ViA^') if has(r.get('ViA^')) else indication.index_position
    length = next((abs(r[k]) for k in ('Length', 'Width', 'S(m-r)') if has(r.get(k))), None)
    depth = next((r[k] for k in ('DA^', 'A/-I/') if has(r.get(k))), None)
    thickness = next((r[k] for k in ('TminZ', 'T(B/-A/)', 'A/-I/') if has(r.get(k))), None)
    amplitude = next((r[k] for k in ('Peak%', 'A%') if has(r.get(k))), None)
    stem = os.path.splitext(indication.file_name)[0]

    def fmt(metres):
        return _length(metres, units)

    def pair(a, b):
        return f'{_length(a, units)} - {_length(b, units)}' if has(a) and has(b) else _length(a if has(a) else b, units)

    return {
        'scan_id': f'{stem} #{indication.number}' if numbered else stem,
        'scan_start': fmt(scan_start),
        'scan_stop': fmt(scan_stop),
        'scan_range': pair(min(s_ref, s_meas), max(s_ref, s_meas)) if both_s else fmt(scan_start),
        'index_pos': fmt(index_pos),
        'index_range': pair(min(i_ref, i_meas), max(i_ref, i_meas)) if both_i else fmt(index_pos),
        'length': fmt(length),
        'depth': fmt(depth),
        'height': fmt(abs(u_meas - u_ref)) if has(u_ref) and has(u_meas) else '',
        'amplitude': f'{amplitude:.1f}' if has(amplitude) else '',
        'thickness_min': fmt(thickness),
        'thickness_avg': fmt(r.get('TavgZ')) if has(r.get('TavgZ')) else '',
        'angle': f'{indication.angle:g}°' if has(indication.angle) else '',
        'comment': indication.comment or '',
    }


def report_columns(report):
    """The report's results headings: its table's own, else its report type's."""
    table = getattr(report, 'results_table', None)
    if table is not None and table.columns:
        return list(table.columns)
    return list(get_report_type(report.report_type).results_headings)


def preview(report, indications, units='in'):
    """{columns, fields, rows}: a row per indication, in the report's columns, for the user to check and edit."""
    columns = report_columns(report)
    type_columns = get_report_type(report.report_type).results_columns
    fields = [field_for(h, type_columns) for h in columns]
    per_file = {}
    for ind in indications:
        per_file[ind.file_path] = per_file.get(ind.file_path, 0) + 1
    rows = []
    for ind in indications:
        rows.append([
            indication_values(ind, units_for(h, units), numbered=per_file[ind.file_path] > 1).get(f, '') if f else ''
            for h, f in zip(columns, fields)
        ])
    return {'columns': columns, 'fields': fields, 'rows': rows}


def _png(data_url):
    """The bytes of a 'data:image/png;base64,...' picture, or None."""
    if not data_url:
        return None
    head, _, body = str(data_url).partition(',')
    if not head.startswith('data:image/png;base64') or not body:
        raise ExportError('Pictures must be PNG.')
    try:
        return base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise ExportError("A picture couldn't be read.")


@transaction.atomic
def append(report, columns, rows, pictures=None, captions=None):
    """
    Adds `rows` (cells in `columns`, as the preview gave them, maybe edited) after the report's own
    rows, and each row's picture (PNG data URL or None). Returns how many rows were added.
    """
    if report.is_issued:
        raise ExportError('This report is issued - reopen it before adding indications.')
    pictures = pictures or [None] * len(rows)
    captions = captions or [''] * len(rows)
    if len(pictures) != len(rows) or len(captions) != len(rows):
        raise ExportError('Each row needs its picture (or none).')
    table = getattr(report, 'results_table', None)
    if table is None:
        table = ResultsTable.objects.create(report=report, columns=list(columns))
    elif not table.columns:
        table.columns = list(columns)
        table.save(update_fields=['columns'])
    if list(table.columns) != list(columns):
        raise ExportError("The report's results columns changed - check the rows again.")
    weld = report.report_type == WELD_TYPE
    scan_id_at = next((i for i, h in enumerate(columns)
                       if field_for(h, get_report_type(report.report_type).results_columns) == 'scan_id'), None)
    order = (table.rows.order_by('-order').values_list('order', flat=True).first() or 0) + 1
    image_order = (report.images.order_by('-order').values_list('order', flat=True).first() or 0) + 1
    for row, picture, caption in zip(rows, pictures, captions):
        cells = [str(v if v is not None else '')[:2000] for v in row][:len(columns)]
        cells += [''] * (len(columns) - len(cells))
        png = _png(picture)
        key = ''
        if weld:   # the weld form's indication key, one cell after the row (its picture hangs on it)
            key = 'ind-' + secrets.token_hex(6)
            cells.append(key)
        ResultsRow.objects.create(table=table, cells=cells, order=order)
        order += 1
        if png:
            scan_id = key if weld else (cells[scan_id_at] if scan_id_at is not None else '')
            image = ReportImage(report=report, kind=ReportImage.INDICATION if weld else ReportImage.SCAN,
                                scan_id=scan_id, caption='' if weld or scan_id else caption[:200], order=image_order)
            image.image.save(f'analysis_{report.pk}_{order}.png', ContentFile(png), save=False)
            image.save()
            image_order += 1
    # Newer than any editor tab open on it, so that tab warns before saving over these rows
    Report.objects.filter(pk=report.pk).update(updated_at=timezone.now())
    return len(rows)


def draft_reports(nde_path='', limit=40):
    """Draft reports to send to, newest first; those whose job folder holds this file come first."""
    folder = os.path.normcase(os.path.dirname(nde_path)) if nde_path else ''
    out = []
    for report in Report.objects.filter(status=Report.DRAFT).order_by('-updated_at', '-pk')[:limit]:
        job = os.path.normcase(report.job_folder or '')
        here = bool(job and folder and (folder == job or folder.startswith(job + os.sep)))
        out.append({'id': report.pk, 'name': report.document_filename or f'Report {report.pk}',
                    'type': get_report_type(report.report_type).label, 'client': report.client,
                    'updated': report.updated_at.isoformat() if report.updated_at else '', 'this_job': here})
    out.sort(key=lambda r: not r['this_job'])   # stable: newest first within each
    return out
