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

from .. import weld_form
from ..models import ReportImage
from ..report_types import get_report_type
from ..results import report_results
from .office import lock, office_app_available
from .report_render import length_unit, velocity_unit, with_unit
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

# The reference form's 'Encoded Scan Plan Images' sheet (password protected: pictures can be
# added; only the Notes and page cells are unlocked). Its four picture boxes, by probe position
# (rows: first / second index offset) and skew (columns: 90 / 270 deg).
SCAN_PLAN_SHEET = 'Encoded Scan Plan Images'
SCAN_PLAN_BOXES = {(1, 90): 'B5:D19', (1, 270): 'E5:G19', (2, 90): 'B22:D36', (2, 270): 'E22:G36'}
SCAN_PLAN_NOTES = {1: 'C20', 2: 'C37'}
SCAN_PLAN_PAGE = 'G4'
XL_SHAPE_RECTANGLE = 1


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
        f'{col}19': _v(setup.cable_type),
        f'{col}20': _v(setup.cable_length),
        f'{col}21': _v(setup.transducer_serial),
        f'{col}22': _v(setup.wedge_material),
        f'{col}23': _v(setup.wedge_model),
        f'{col}24': with_unit(setup.wedge_angle, '°'),
        f'{col}25': with_unit(setup.specimen_od, length_unit(setup)),
        f'{col}26': _v(setup.wedge_curve),
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
        f'{col}22': _v(setup.focal_plane),
        f'{col}23': with_unit(setup.foc_depth, length_unit(setup)),
        f'{col}24': _v(setup.time_base),
        f'{col}25': with_unit(setup.voltage, ' V'),
        f'{col}26': _v(setup.points_quantity),
        f'{col}27': _v(setup.smoothing),
        f'{col}28': with_unit(setup.band_pass_filter, ' MHz'),
        f'{col}29': _v(setup.amplitude_range),
        f'{col}30': with_unit(setup.gain, ' dB'),
        f'{col}31': _v(setup.transfer_db),
        f'{col}32': _v(setup.scanning_db),
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
            'C19': _v(first.scope_cal_due),
            'C20': _v(first.module_model),
            'C21': _v(first.module_serial),
            'C22': _v(first.module_cal_due),
            'C23': _v(first.software_version),
            'C24': _v(first.scanner_type),
            'C25': _v(first.scanner_model),
            'C26': _v(first.analysis_software),
            'C27': _v(first.analysis_software_version),
            'C33': _v(first.encoder_resolution),
            'C35': _v(first.scan_speed),
            'W24': _v(first.exam_surface), 'Y24': _v(first.exam_surface),
            'W25': _v(first.couplant), 'Y25': _v(first.couplant),
            'C34': with_unit(first.x_res, length_unit(first)),
        })
        velocity = with_unit(first.sound_velocity, velocity_unit(first))
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
            'Y20': with_unit(first.specimen_od, length_unit(first)),
            'Y21': with_unit(first.specimen_thickness, length_unit(first)),
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


KIND_KEY = {'paut': 'PAUT', 'conv_long': '0deg', 'conv_shear': 'SW'}


def _probe_keys(probes):
    """'PAUT 1: Olympus 10L32-A1', '0deg 1: Olympus D791', ... as the reference's Probe Table names them."""
    keys, counts = {}, {}
    for probe in probes:
        if probe.kind == weld_form.NOT_USED:
            keys[probe.pk] = 'N/A'
            continue
        prefix = KIND_KEY.get(probe.kind, 'PAUT')
        counts[prefix] = counts.get(prefix, 0) + 1
        name = ' '.join(v for v in (_v(probe.make), _v(probe.model)) if v)
        keys[probe.pk] = f'{prefix} {counts[prefix]}: {name}' if name else f'{prefix} {counts[prefix]}'
    return keys


def _grid(report):
    """
    The testing instrument, probe columns (F-I) and group columns (L, N, P, Q, S) from the report's
    equipment grid (reports/weld_form.py has the rows and the N/A rows per probe kind).
    """
    probes = list(report.probes.all())
    groups = list(report.groups.select_related('probe'))
    keys = _probe_keys(probes)
    cells = {}
    for name, _, row in weld_form.INSTRUMENT_ROWS:
        cells[f'{"A" if row == 15 else "C"}{row}'] = _v(getattr(report, name))

    for i, col in enumerate(weld_form.PROBE_COLUMNS):
        if i >= len(probes):
            cells.update(_unused_column(col, range(15, 31)))
            continue
        probe = probes[i]
        na = weld_form.PROBE_NA.get(probe.kind, set())
        cells[f'{col}13'] = f'Probe {i + 1}\n({probe.label})' if _v(probe.label) else f'Probe {i + 1}'
        if probe.kind == weld_form.NOT_USED:
            cells.update(_unused_column(col, range(15, 31)))
            continue
        cells[f'{col}15'] = keys[probe.pk]
        for name, _, row in weld_form.PROBE_ROWS:
            cells[f'{col}{row}'] = 'N/A' if name in na else _v(getattr(probe, name))
        used = [str(j + 1) for j, group in enumerate(groups) if group.probe_id == probe.pk]
        # Three rows: a 4th or 5th group on the probe joins the last one ('3, 4, 5')
        last = len(weld_form.RELEVANT_GROUP_ROWS) - 1
        used = used[:last] + [', '.join(used[last:])] if len(used) > last else used
        for k, row in enumerate(weld_form.RELEVANT_GROUP_ROWS):
            cells[f'{col}{row}'] = used[k] if k < len(used) else 'N/A'

    for i, col in enumerate(weld_form.GROUP_COLUMNS):
        if i >= len(groups):
            cells.update(_unused_column(col, range(15, 33)))
            continue
        group = groups[i]
        kind = group.probe.kind if group.probe else weld_form.PAUT
        na = weld_form.GROUP_NA.get(kind, set())
        cells[f'{col}13'] = f'Group {i + 1} ({group.label})' if _v(group.label) else f'Group {i + 1}'
        if group.not_applicable or kind == weld_form.NOT_USED:
            cells.update(_unused_column(col, range(15, 33)))
            continue
        cells[f'{col}15'] = keys.get(group.probe_id, 'N/A')
        for name, _, row in weld_form.GROUP_ROWS:
            cells[f'{col}{row}'] = 'N/A' if name in na else _v(getattr(group, name))
    return cells


def _with_block(equipment, block):
    """
    The setup's cells with the sensitivity block's on top, except where the setup gives a value
    for the scanner, scan speed or couplant (the block's are only its usual ones).
    """
    setup_first = {'C25', 'C35', 'W25', 'Y25'}
    merged = dict(equipment)
    for ref, value in block.items():
        if ref in setup_first and equipment.get(ref):
            continue
        merged[ref] = value
    return merged


def _tcg_distances(depth):
    """
    TCG distances from the block's notch / SDH depth, as the reference workbook works them out:
    1×, 2× and 3× the depth, or 1×, 3× and 6× for 0.1875" side-drilled holes.
    """
    try:
        d = float(depth)
    except (TypeError, ValueError):
        return {}
    second, third = (3, 6) if abs(d - 0.1875) < 1e-6 else (2, 3)
    return {'L36': f'{d:.3f}', 'N36': f'{d * second:.3f}', 'P36': f'{d * third:.3f}'}


def _block(report):
    """
    Material Information, encoder and TCG cells from the scan plan's sensitivity block (the
    weld form's Cal Block Table row); these take precedence over the setup's values.
    """
    plan = report.scan_plan
    block = plan.sensitivity_block if plan is not None else None
    if block is None:
        return {}
    cells = {
        'U15': _v(block.pipe_size),
        # Calibration standard
        'W14': _v(block.serial_number), 'W16': _v(block.block_type), 'W17': _v(block.material),
        'W18': _v(block.velocity_shear), 'W19': _v(block.velocity_long), 'W20': _v(block.cal_diameter),
        'W21': _v(block.cal_sch_nom), 'W22': _v(block.temperature), 'W23': _v(block.surface_cal),
        'W25': _v(block.couplant),
        # Item inspected
        'Y17': _v(block.material), 'Y18': _v(block.velocity_shear), 'Y19': _v(block.velocity_long),
        'Y20': _v(block.test_diameter), 'Y21': _v(block.test_sch_nom), 'Y22': _v(block.temperature),
        'Y23': _v(block.surface_test), 'Y25': _v(block.couplant), 'Y26': _v(block.bevel_geometry),
        # Scanner and encoder
        'C25': _v(block.encoder), 'C33': _v(block.encoder_steps), 'C34': _v(block.scan_res),
        'C35': _v(block.scan_speed),
        # TCG
        'L34': _v(block.serial_number), 'Q34': _v(block.serial_number),
        'L35': _v(block.block_type), 'N35': _v(block.block_type), 'P35': _v(block.block_type),
        **_tcg_distances(block.reflector_depth),
    }
    return {ref: value for ref, value in cells.items() if value}


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


def _equipment_cells(report, setups):
    """
    Equipment from the report's probe / group grid when it has one (material information still
    from the first setup), else from its setups (reports from before the grid).
    """
    cells = _equipment(setups)
    if report.pk and (report.probes.exists() or report.groups.exists()):
        cells.update(_grid(report))
    return cells


def weld_pages(report):
    """Every value of the weld report and where it goes."""
    setups = list(report.setups.order_by('order', 'pk'))
    _, rows = report_results(report)
    report_cells, continuation = _results(rows)
    pages = WeldPages(
        report={**_header(report), **_with_block(_equipment_cells(report, setups), _block(report)),
                **_calibration(report), **report_cells},
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


def _fill(wb, pages, scan_plan_pictures):
    report = wb.Worksheets('Report')
    master = wb.Worksheets('Indication')
    continuation = wb.Worksheets('Continuation')
    plan_sheet = wb.Worksheets(SCAN_PLAN_SHEET)
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
            _add_picture_in(ws, ind.image_path, INDICATION_PICTURE)
    master.Delete()

    plan = pages.scan_plan
    if plan is not None:
        plan_sheet.Move(None, wb.Worksheets(wb.Worksheets.Count))  # last page, as on the paper form
        plan_sheet.Range(SCAN_PLAN_PAGE).Value = f"'{total} of {total}"
        if plan.notes:
            _write(plan_sheet, {SCAN_PLAN_NOTES[1]: plan.notes})
        for key, box in SCAN_PLAN_BOXES.items():
            if key in scan_plan_pictures:
                _add_picture_in(plan_sheet, scan_plan_pictures[key], box)
            else:
                _blank_box(plan_sheet, box)  # its 'Insert Scan Plan Image Here' text is locked
    else:
        plan_sheet.Delete()
    report.Activate()


def _add_picture_in(ws, path, box):
    """The picture, as large as fits the cell range `box`, centred in it."""
    area = ws.Range(box)
    pad = 3  # points inside the box's borders
    left, top, width, height = area.Left + pad, area.Top + pad, area.Width - 2 * pad, area.Height - 2 * pad
    pic = ws.Shapes.AddPicture(path, False, True, left, top, -1, -1)
    pic.LockAspectRatio = True
    scale = min(width / pic.Width, height / pic.Height)
    pic.Width = pic.Width * scale
    pic.Left = left + (width - pic.Width) / 2
    pic.Top = top + (height - pic.Height) / 2


def _blank_box(ws, box):
    """A plain white cover over an unused picture box, inside its borders."""
    area = ws.Range(box)
    cover = ws.Shapes.AddShape(XL_SHAPE_RECTANGLE, area.Left + 1.5, area.Top + 1.5, area.Width - 3, area.Height - 3)
    cover.Fill.ForeColor.RGB = 0xFFFFFF
    cover.Line.Visible = False


def _scan_plan_pictures(plan, workdir):
    """
    The scan plan drawings written to PNG files for Excel, one per ticked skew per index offset:
    {(position, skew): path}.
    """
    paths = {}
    for position, _, skew in plan.drawings if plan else ():
        side = 1 if skew == 90 else 2
        path = os.path.join(workdir, f'scan_plan_{position}_{skew}.png')
        with open(path, 'wb') as f:
            f.write(render_png(plan, side, position))
        paths[(position, skew)] = path
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
