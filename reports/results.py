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


def report_scan_rows(report):
    table = getattr(report, 'results_table', None) if report is not None and report.pk else None
    if table is None:
        return []
    return scan_rows(table.columns, [r.cells for r in table.rows.all()])
