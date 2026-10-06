"""
Scan IDs and comments from a report's results table.

The first column is the Scan ID. Comments come from the column whose header mentions
"result" or "comment" (e.g. "Results"), otherwise the last column. Photo-summary images are
tied to a results row by its Scan ID text and take their comments from that row.
The editor's JavaScript (create_report.js, resultsScanRows) follows the same rules.
"""
import re

COMMENT_HEADER = re.compile(r'result|comment', re.IGNORECASE)


def comments_column(columns):
    for i, name in enumerate(columns or []):
        if i > 0 and COMMENT_HEADER.search(name or ''):
            return i
    return len(columns or []) - 1


def scan_rows(columns, rows):
    """[(scan_id, comments)] in table order, skipping rows without a Scan ID."""
    ci = comments_column(columns)
    out = []
    for cells in rows or []:
        cells = list(cells or [])
        scan_id = (cells[0] if cells else '').strip()
        if not scan_id:
            continue
        comments = cells[ci] if 0 < ci < len(cells) else ''
        out.append((scan_id, comments or ''))
    return out


def _norm(heading):
    return re.sub(r'[^a-z0-9]', '', (heading or '').lower())


def fit_to_columns(columns, rows, headings):
    """
    Re-arranges a results table (columns, rows) to the fixed `headings` of a report type.
    A heading takes the old column with the same name (ignoring case and punctuation), else
    the next unused old column by position. Old columns left over are appended to the last
    column's text as 'Heading: value', so no data is lost.
    """
    columns = list(columns or [])
    headings = list(headings)
    if not headings or columns == headings:
        return headings or columns, [list(r) for r in rows or []]

    source_for = {}
    used = set()
    by_name = {_norm(c): i for i, c in reversed(list(enumerate(columns)))}
    for ti, heading in enumerate(headings):
        si = by_name.get(_norm(heading))
        if si is not None and si not in used:
            source_for[ti] = si
            used.add(si)
    leftovers = [i for i in range(len(columns)) if i not in used]
    for ti in range(len(headings)):
        if ti not in source_for and leftovers:
            source_for[ti] = leftovers.pop(0)

    fitted = []
    for cells in rows or []:
        cells = list(cells or [])
        new = [cells[source_for[ti]] if ti in source_for and source_for[ti] < len(cells) else ''
               for ti in range(len(headings))]
        extra = [f'{columns[si]}: {cells[si]}' for si in leftovers if si < len(cells) and (cells[si] or '').strip()]
        if extra:
            new[-1] = '\n'.join([new[-1]] + extra) if new[-1] else '\n'.join(extra)
        fitted.append(new)
    return headings, fitted


def report_scan_rows(report):
    return scan_rows(*report_results(report))


def report_results(report):
    """(columns, rows) of a report's results table, fitted to its report type's fixed columns."""
    from .report_types import get_report_type
    table = getattr(report, 'results_table', None) if report is not None and report.pk else None
    if table is None:
        return [], []
    headings = get_report_type(report.report_type).results_headings
    return fit_to_columns(table.columns, [r.cells for r in table.rows.all()], headings)
