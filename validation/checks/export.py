"""
L5 (second half) - export: indications sent to every report type's results table, checked column by
column against the indication's own values written out here by the rule (the column's units from its
heading - mm to 0.1, inches to 0.001 - amplitude to 0.1 %), then read back from the saved rows. All
inside a database transaction that is always rolled back: nothing is left in the reports.
"""
from django.db import transaction

from analysis.models import Indication
from analysis.services import report_export
from reports.models import Report
from reports.report_types import REPORT_TYPES

from . import check, item

AGAINST = "The indication's own values"
IN = 0.0254
# What each report type's own column takes - the export's specification, written down here
SPEC = {
    'scan_id': 'scan_id', 'circ_start': 'scan_start', 'length': 'length', 'axial_pos': 'index_pos', 'depth': 'depth',
    'height': 'height', 'amp': 'amplitude', 'comments': 'comment', 'min_thk': 'thickness_min', 'avg_thk': 'thickness_avg',
    'x_range': 'scan_range', 'circ': 'scan_range', 'y_range': 'index_range', 'axial': 'index_range',
}


class _RolledBack(Exception):
    pass


def _indications():
    """Two indications on one weld file, found and sized, with every value set (m, %)."""
    common = dict(file_path=r'C:\validation\weld 7.nde', file_name='weld 7.nde', group=0, angle=55.0, gain=0.0,
                  source=Indication.AUTO, status=Indication.ACCEPTED)
    return [
        Indication(number=1, scan=120, lateral=12, scan_position=0.1204, index_position=-0.0143, comment='Validation 1',
                   readings={'A%': 87.4321, 'DA^': 0.012345, 'ViA^': 0.006789, 'S(m-r)': 0.0127, 'TminZ': 0.009876, 'TavgZ': 0.0101},
                   sizing={'auto': True, 'scan_start': 0.11507, 'scan_end': 0.12795, 'length': 0.01288, 'height': 0.00271,
                           'depth': 0.011112, 'axial': 0.007654, 'axial_start': 0.0061, 'axial_end': 0.0093, 'peak_amplitude': 91.26},
                   **common),
        Indication(number=2, scan=340, lateral=20, scan_position=0.3401, index_position=-0.0121, comment='Validation 2',
                   readings={'A%': 43.05, 'DA^': 0.004441, 'ViA^': 0.011102}, sizing={}, cursors={'s_ref': 0.3391, 's_meas': 0.3502},
                   **common),
    ]


def _fmt(metres, units):
    return '' if metres is None else (f'{metres * 1000:.1f}' if units == 'mm' else f'{metres / IN:.3f}')


def expected(ind, field, units, numbered):
    """The cell a field should hold for an indication: its value as stored, written by the rule."""
    r, s, c = ind.readings or {}, ind.sizing or {}, ind.cursors or {}
    sized = bool(s.get('auto'))
    start = s.get('scan_start') if sized else min(c['s_ref'], c['s_meas']) if 's_ref' in c else ind.scan_position
    stop = s.get('scan_end') if sized else max(c['s_ref'], c['s_meas']) if 's_meas' in c else None
    values = {
        'scan_id': f"weld 7 #{ind.number}" if numbered else 'weld 7',
        'scan_start': _fmt(start, units),
        'scan_range': f'{_fmt(start, units)} - {_fmt(stop, units)}' if stop is not None else _fmt(start, units),
        'length': _fmt(s['length'] if sized else abs(r['S(m-r)']) if 'S(m-r)' in r else None, units),
        'depth': _fmt(s['depth'] if sized else r.get('DA^'), units),
        'height': _fmt(s.get('height') if sized else None, units),
        'amplitude': f"{(s['peak_amplitude'] if sized else r['A%']):.1f}",
        'index_pos': _fmt(s['axial'] if sized else r.get('ViA^'), units),
        'index_range': f"{_fmt(s['axial_start'], units)} - {_fmt(s['axial_end'], units)}" if sized else _fmt(r.get('ViA^'), units),
        'thickness_min': _fmt(r.get('TminZ', r.get('T(B/-A/)', r.get('A/-I/'))), units),
        'thickness_avg': _fmt(r.get('TavgZ'), units),
        'comment': ind.comment,
    }
    return values[field]


def run(context):
    indications = _indications()
    for key, kind in REPORT_TYPES.items():
        if not kind.results_columns:
            continue
        items, read_back = [], None
        try:
            with transaction.atomic():
                report = Report.objects.create(report_type=key, document_title='Validation check (rolled back)')
                shown = report_export.preview(report, indications, units='in')
                report_export.append(report, shown['columns'], shown['rows'])
                read_back = [row.cells[:len(shown['columns'])] for row in report.results_table.rows.order_by('order')]
                raise _RolledBack
        except _RolledBack:
            pass
        headings = dict((h, k) for k, h in kind.results_columns)
        for n, ind in enumerate(indications):
            for col, heading in enumerate(shown['columns']):
                field = SPEC.get(headings.get(heading))
                cell = shown['rows'][n][col]
                saved = read_back[n][col] if read_back and n < len(read_back) else None
                if field is None:
                    if cell:
                        items.append(item(f'#{ind.number} {heading}', 'not one of its own fields', repr(cell), None, 'Filled by the heading'))
                    continue
                want = expected(ind, field, report_export.units_for(heading, 'in'), numbered=True)
                items.append(item(f'#{ind.number} {heading}', repr(want), repr(cell) + ('' if saved == cell else f' (saved as {saved!r})'),
                                  cell == want and saved == cell, 'The value, in the column\'s units, saved unchanged'))
        context.emit(check('Export', f"{kind.label if hasattr(kind, 'label') else key} ({key})", AGAINST, items,
                           note='Two indications (one sized, one by its cursors) sent and read back inside a transaction that was rolled back.'))
