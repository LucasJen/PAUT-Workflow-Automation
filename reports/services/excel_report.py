"""
Excel weld report (form 100-UTFORM-010): fills excel_templates/paut_weld.xlsx through Excel.

weld_pages(report) works out every value and where it goes (pure Python, unit tested);
build_workbook(report) writes them with a separate, hidden Excel instance, adds one
Indication page per flaw with its scan image and the Scan Plan page with the report's scan
plan drawings, saves the .xlsx and optionally exports the PDF.
The template's cell positions are described in excel_templates/TEMPLATE_CELLS.md.
"""
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime

from django.conf import settings

from ..models import ReportImage
from ..report_types import get_report_type
from ..results import report_results
from .office import lock, office_app_available
from .report_render import with_unit
from .scan_plan import render_png

logger = logging.getLogger(__name__)

XL_OPEN_XML_WORKBOOK = 51
XL_TYPE_PDF = 0
XL_QUALITY_STANDARD = 0

CHECK = 'P'     # a check mark in the template's Wingdings 2 Accept column
CROSS = '☓'

# Report sheet layout
PROBE_COLUMNS = 'FGHI'               # Probe 1–4
GROUP_COLUMNS = 'LNPQS'              # Group 1–5
REPORT_RESULT_ROWS = range(41, 53)   # 12 rows on page 1
CONTINUATION_ROWS = range(15, 48)    # 33 rows on the Continuation page
RESULT_COLUMNS = 'ACDEFGHIJKLMNOPQ'  # Weld ID … Type, in WELD_RESULTS_COLUMNS order
ACCEPT_COLUMN, REJECT_COLUMN, COMMENTS_COLUMN = 'S', 'T', 'U'
CAL_ROWS = (34, 35, 36, 37)          # Initial, Cal. Check, Cal. Check, Cal. Out
INDICATION_PICTURE = 'A12:Z56'


class ExcelReportError(Exception):
    """Excel could not produce the report."""


def excel_available():
    """True when Excel output is enabled and Excel is installed on this machine."""
    return office_app_available('Excel.Application')


@dataclass
class Indication:
    weld_id: str
    number: int           # 1, 2, ... within its weld
    notes: str
    image_path: str = ''


@dataclass
class WeldPages:
    report: dict = field(default_factory=dict)        # cell -> value on the Report sheet
    continuation: dict = field(default_factory=dict)  # cell -> value; empty = no Continuation page
    indications: list = field(default_factory=list)
    scan_plan: object = None                          # ScanPlan, printed on the last page

    @property
    def page_count(self):
        return 1 + bool(self.continuation) + len(self.indications) + bool(self.scan_plan)


# ── Values ───────────────────────────────────────────────────────────────

def _v(value):
    return (value or '').strip()


def _setup_key(setup):
    """Column heading key, e.g. 'PAUT 1: 10L32-A1' (Technique title, then the probe model)."""
    model = _v(setup.transducer_model)
    title = _v(setup.title)
    return f'{title}: {model}' if title and model else title or model


def _vpa(setup):
    """Elements per virtual aperture / VPA index; N/A when the group doesn't step an aperture."""
    if 'sector' in _v(setup.beam_formation).lower() or not (setup.element_aperture and setup.element_step):
        return 'N/A'
    return f'{setup.element_aperture} ele / {setup.element_step} ele'


def _probe_column(col, setup, group_number):
    return {
        f'{col}15': _setup_key(setup),
        f'{col}16': _v(setup.manufacturer),
        f'{col}17': _v(setup.transducer_model),
        f'{col}18': with_unit(setup.freq, ' MHz'),
        f'{col}21': _v(setup.transducer_serial),
        f'{col}23': _v(setup.wedge_model),
        f'{col}24': with_unit(setup.wedge_angle, '°'),
        f'{col}25': with_unit(setup.specimen_od, '"'),
        f'{col}27': 'Accept',
        f'{col}28': str(group_number),
        f'{col}29': 'N/A',
        f'{col}30': 'N/A',
    }


def _group_column(col, setup):
    return {
        f'{col}15': _setup_key(setup),
        f'{col}16': _v(setup.beam_formation),
        f'{col}17': _v(setup.wave_propagation),
        f'{col}18': _v(setup.angle_range),
        f'{col}19': _v(setup.active_elements),
        f'{col}20': with_unit(setup.angle_step, '°'),
        f'{col}21': _vpa(setup),
        f'{col}23': with_unit(setup.foc_depth, '"'),
        f'{col}25': with_unit(setup.voltage, ' V'),
        f'{col}28': with_unit(setup.band_pass_filter, ' MHz'),
        f'{col}30': with_unit(setup.gain, ' dB'),
    }


def _unused_column(col, rows):
    return {f'{col}{r}': 'N/A' for r in rows}


def _equipment(setups):
    cells = {}
    first = setups[0] if setups else None
    if first is not None:
        cells.update({
            'A15': _v(first.scope_platform) or _v(first.scope_model),
            'C16': _v(first.manufacturer),
            'C17': _v(first.scope_model),
            'C18': _v(first.scope_serial),
            'C33': _v(first.encoder_resolution),
            'C34': with_unit(first.x_res, '"'),
        })
        velocity = with_unit(first.sound_velocity, ' in/µs')
        velocity_row = 19 if _v(first.wave_propagation) == 'Longitudinal' else 18
        cells.update({
            # Calibration standard
            'W14': _v(first.cal_block_serial),
            'W16': _v(first.cal_block_type),
            'W17': _v(first.cal_material),
            f'W{velocity_row}': velocity,
            'W22': _v(first.material_temp),
            # Item inspected
            'Y17': _v(first.cal_material),
            f'Y{velocity_row}': velocity,
            'Y20': with_unit(first.specimen_od, '"'),
            'Y21': with_unit(first.specimen_thickness, '"'),
            'Y22': _v(first.material_temp),
            'Y23': _v(first.surface_prep),
            # TCG
            'L34': _v(first.cal_block_serial),
            'Q34': _v(first.cal_block_serial),
            'L35': _v(first.cal_block_type),
        })
    for i, col in enumerate(PROBE_COLUMNS):
        cells.update(_probe_column(col, setups[i], i + 1) if i < len(setups) else _unused_column(col, range(15, 31)))
    for i, col in enumerate(GROUP_COLUMNS):
        cells.update(_group_column(col, setups[i]) if i < len(setups) else _unused_column(col, range(15, 33)))
    return cells


def _calibration(report):
    cells = {}
    times = (report.cal_time_initial, report.cal_time_check1, report.cal_time_check2, report.cal_time_out)
    for row, time in zip(CAL_ROWS, times):
        if _v(time):
            cells[f'F{row}'] = _v(time)
            cells.update({f'{col}{row}': 'Accept' for col in 'GHI'})
    return cells


def _person(people, role):
    return next((p for p in people if getattr(p, role)), None)


def _header(report):
    people = list(report.people.all())
    technician = _person(people, 'examined') or _person(people, 'prepared')
    reviewer = _person(people, 'reviewed')
    return {
        'X2': _v(report.document_filename),
        'X3': report.report_date,
        'X5': _v(report.work_order),
        'C7': _v(report.client),
        'C8': _v(report.address),
        'C9': _v(report.contractor),
        'C10': _v(report.item_description),
        'C11': _v(report.exam_code),
        'L11': _v(report.acceptance_standard),
        'U11': _v(report.procedure),
        'Z11': _v(report.procedure_rev),
        'C39': _v(report.location),
        'C53': _v(report.notes),
        'C55': technician.name if technician else '',
        'R55': technician.certification if technician else '',
        'C57': reviewer.name if reviewer else '',
        'R57': reviewer.certification if reviewer else '',
    }


def _result_cells(cells, row):
    """Cell values for one results row (WELD_RESULTS_COLUMNS order) on sheet row `row`."""
    cells = list(cells) + [''] * (len(RESULT_COLUMNS) + 2 - len(cells))
    out = {f'{col}{row}': _v(value) for col, value in zip(RESULT_COLUMNS, cells)}
    verdict = _v(cells[len(RESULT_COLUMNS)]).lower()
    if verdict.startswith(('a', 'p', '✓')):
        out[f'{ACCEPT_COLUMN}{row}'] = CHECK
    elif verdict.startswith(('r', 'f', 'x', '☓')):
        out[f'{REJECT_COLUMN}{row}'] = CROSS
    out[f'{COMMENTS_COLUMN}{row}'] = _v(cells[len(RESULT_COLUMNS) + 1])
    return out


def _results(rows):
    """(report cells, continuation cells) for the results rows."""
    rows = [r for r in rows if any(_v(c) for c in r)]
    report_cells, continuation = {}, {}
    page1 = len(REPORT_RESULT_ROWS)
    for row, cells in zip(REPORT_RESULT_ROWS, rows[:page1]):
        report_cells.update(_result_cells(cells, row))
    for row, cells in zip(CONTINUATION_ROWS, rows[page1:]):
        continuation.update(_result_cells(cells, row))
    if len(rows) > page1 + len(CONTINUATION_ROWS):
        logger.warning('Weld report has %s results rows; only %s fit', len(rows), page1 + len(CONTINUATION_ROWS))
    return report_cells, continuation


def _indications(report, rows):
    """One Indication page per row with a flaw Type; the n-th flaw of a weld takes its n-th scan image."""
    images = {}
    for image in report.images.filter(kind=ReportImage.SCAN).order_by('order'):
        if image.image:
            images.setdefault(_v(image.scan_id), []).append(image.image.path)
    type_index = RESULT_COLUMNS.index('Q')
    out, weld, counts = [], '', {}
    for cells in rows:
        cells = list(cells) + [''] * (len(RESULT_COLUMNS) + 2 - len(cells))
        weld = _v(cells[0]) or weld
        if not _v(cells[type_index]):
            continue
        counts[weld] = counts.get(weld, 0) + 1
        n = counts[weld]
        weld_images = images.get(weld, [])
        out.append(Indication(weld, n, _v(cells[-1]), weld_images[n - 1] if n <= len(weld_images) else ''))
    return out


def weld_pages(report):
    """Every value of the weld report and where it goes."""
    setups = list(report.setups.order_by('order', 'pk'))
    _, rows = report_results(report)
    report_cells, continuation = _results(rows)
    pages = WeldPages(
        report={**_header(report), **_equipment(setups), **_calibration(report), **report_cells},
        continuation=continuation,
        indications=_indications(report, rows),
        scan_plan=report.scan_plan,
    )
    if pages.continuation:
        pages.continuation['C13'] = _v(report.location)
    return pages


# ── Excel ────────────────────────────────────────────────────────────────

def template_path(report):
    return os.path.join(settings.BASE_DIR, 'excel_templates', get_report_type(report.report_type).template)


def _write(ws, cells):
    for ref, value in cells.items():
        if value in (None, ''):
            continue
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)  # COM takes datetimes
        elif isinstance(value, str):
            value = "'" + value  # stored as typed: keeps 0.280 and 0700 as text, never a formula
        ws.Range(ref).MergeArea.Cells(1, 1).Value = value


def _page_numbers(ws, page, total):
    ws.Range('X4').Value = page
    ws.Range('Z4').Value = total


def _add_picture(ws, path, part=0, parts=1):
    """
    The picture, as large as fits the picture area, centred. With parts > 1 the area is split
    into equal side-by-side columns and the picture goes in column `part`.
    """
    area = ws.Range(INDICATION_PICTURE)
    gap = 6  # points between side-by-side pictures
    width = (area.Width - gap * (parts - 1)) / parts
    left = area.Left + part * (width + gap)
    pic = ws.Shapes.AddPicture(path, False, True, left, area.Top, -1, -1)
    pic.LockAspectRatio = True
    scale = min(width / pic.Width, area.Height / pic.Height)
    pic.Width = pic.Width * scale
    pic.Left = left + (width - pic.Width) / 2
    pic.Top = area.Top + (area.Height - pic.Height) / 2


def _fill(wb, pages, scan_plan_pictures):
    report = wb.Worksheets('Report')
    master = wb.Worksheets('Indication')
    continuation = wb.Worksheets('Continuation')
    plan_sheet = wb.Worksheets('Scan Plan')
    total = pages.page_count

    _write(report, pages.report)
    _page_numbers(report, 1, total)
    page = 1
    if pages.continuation:
        continuation.Move(None, report)  # (Before, After) by position: keywords are ignored late-bound
        _write(continuation, pages.continuation)
        page += 1
        _page_numbers(continuation, page, total)
    else:
        continuation.Delete()

    for i, ind in enumerate(pages.indications, start=1):
        count = wb.Worksheets.Count
        master.Copy(None, wb.Worksheets(count))
        if wb.Worksheets.Count != count + 1:
            raise ExcelReportError('Excel did not add the Indication page.')
        ws = wb.Worksheets(count + 1)
        ws.Name = f'Indication {i}'
        _write(ws, {'C57': ind.weld_id, 'L57': str(ind.number), 'C60': ind.notes})
        page += 1
        _page_numbers(ws, page, total)
        if ind.image_path and os.path.exists(ind.image_path):
            _add_picture(ws, ind.image_path)
    master.Delete()

    plan = pages.scan_plan
    if plan is not None:
        plan_sheet.Move(None, wb.Worksheets(wb.Worksheets.Count))  # last page, as on the paper form
        _write(plan_sheet, {'C57': plan.name, 'L57': plan.pipe_size, 'C60': plan.notes})
        _page_numbers(plan_sheet, total, total)
        for part, path in enumerate(scan_plan_pictures):
            _add_picture(plan_sheet, path, part, len(scan_plan_pictures))
    else:
        plan_sheet.Delete()
    report.Activate()


def _scan_plan_pictures(plan, workdir):
    """The scan plan drawings written to PNG files for Excel, one per side."""
    paths = []
    for side in plan.side_numbers if plan else ():
        path = os.path.join(workdir, f'scan_plan_{side}.png')
        with open(path, 'wb') as f:
            f.write(render_png(plan, side))
        paths.append(path)
    return paths


def build_workbook(report, pdf=False):
    """
    (xlsx bytes, pdf bytes or None) for a weld report. Raises ExcelReportError on failure.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise ExcelReportError('Excel output needs the pywin32 package (pip install pywin32).') from e

    pages = weld_pages(report)
    workdir = tempfile.mkdtemp(prefix='report-xlsx-')
    xlsx_path = os.path.join(workdir, 'report.xlsx')
    pdf_path = os.path.join(workdir, 'report.pdf')
    shutil.copyfile(template_path(report), xlsx_path)
    scan_plan_pictures = _scan_plan_pictures(pages.scan_plan, workdir)

    with lock:
        pythoncom.CoInitialize()  # COM must be initialised on each request thread
        excel = wb = None
        try:
            excel = win32com.client.DispatchEx('Excel.Application')  # separate instance
            excel.Visible = False
            excel.DisplayAlerts = False
            excel.ScreenUpdating = False
            wb = excel.Workbooks.Open(xlsx_path, UpdateLinks=0, AddToMru=False)
            _fill(wb, pages, scan_plan_pictures)
            excel.CalculateFull()
            wb.Save()
            if pdf:
                wb.ExportAsFixedFormat(XL_TYPE_PDF, pdf_path, XL_QUALITY_STANDARD, True, False)
        except Exception as e:  # COM errors come in many types
            logger.exception('Excel weld report failed')
            raise ExcelReportError(f'Excel could not create the report: {e}') from e
        finally:
            try:
                if wb is not None:
                    wb.Close(SaveChanges=False)
                if excel is not None:
                    excel.Quit()
            except Exception:
                logger.warning('Could not close Excel cleanly', exc_info=True)
            pythoncom.CoUninitialize()

    try:
        with open(xlsx_path, 'rb') as f:
            xlsx = f.read()
        pdf_bytes = None
        if pdf:
            with open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()
        return xlsx, pdf_bytes
    except OSError as e:
        raise ExcelReportError('Excel finished but the report file was not written.') from e
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
