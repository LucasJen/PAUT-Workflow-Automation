"""
Excel corrosion report (form 598-PAUTFORM-009): fills excel_templates/paut_corrosion.xlsx through
Excel, like the weld form (excel_report.py, which opens Excel and saves / exports).

corrosion_pages(report) works out every value and picture and where it goes (pure Python, unit
tested); fill_corrosion(wb, pages) writes them: the Summary page, a Setup Information page per
setup, a drawing page per drawing (landscape pictures on Horizontal Drawing, portrait ones on
Vertical Drawing) and an Images page per two scan images. Pages with nothing on them aren't
printed: the Thickness Table always goes (the summary is written by the technician), the
Formulas sheet (the method descriptions the setup pages look up) is hidden.
"""
import os
from dataclasses import dataclass, field
from datetime import date

from PIL import Image

from ..models import ReportImage
from ..report_types import CORROSION_METHODS

TITLE = 'Phased Array Ultrasonic Examinations on Selected Areas On'

SUMMARY = 'Summary'
SETUP = 'Setup Information'
HORIZONTAL = 'Horizontal Drawing'
VERTICAL = 'Vertical Drawing'
THICKNESS = 'Thickness Table'
IMAGES = 'Images'
FORMULAS = 'Formulas'
TOTAL_PAGES = 'AO6'
METHOD_DESCRIPTION = 'B5'          # =VLOOKUP(method, Formulas!B1:C9, 2, FALSE)
SETUP_PICTURE = 'B10:AO44'
DRAWING_PICTURE = {HORIZONTAL: 'B5:AT38', VERTICAL: 'B5:AO50'}
# An Images page: (picture box, caption, description) for its first and second image
IMAGE_SLOTS = (('B2:AS18', 'B19', 'K19'), ('B26:AS42', 'B43', 'K43'))
SECOND_IMAGE_ROWS = '23:46'        # hidden on a last page with one image
FOOTER = '&"Times New Roman,Italic"&9Page {page} of {total}'
XL_SHEET_HIDDEN = 0


@dataclass
class SetupPage:
    cells: dict
    method_known: bool        # the Formulas sheet describes it; else the description is left blank
    picture: str = ''


@dataclass
class ImageSlot:
    picture: str
    caption: str = ''
    description: str = ''


@dataclass
class CorrosionPages:
    summary: dict
    setups: list = field(default_factory=list)
    drawings: list = field(default_factory=list)      # [(sheet name, picture path)]
    images: list = field(default_factory=list)        # [[ImageSlot, ImageSlot?]] one list per page

    @property
    def page_count(self):
        return 1 + len(self.setups) + len(self.drawings) + len(self.images)


def _v(value):
    return '' if value is None else str(value).strip()


def _lines(*parts):
    """Non-empty parts on their own lines: 'Lucas Jennings', 'PAUT Level II' -> two lines."""
    return '\n'.join(p for p in (_v(part) for part in parts) if p)


def _serial(model, serial):
    """'Olympus D791', '1009752' -> 'Olympus D791\\nSN: 1009752' (as on the filled forms)."""
    return _lines(model, f'SN: {_v(serial)}' if _v(serial) else '')


def method_name(title):
    """The form's own spelling of a method ('hydroform' -> 'HydroFORM'), or '' when it isn't one of them."""
    wanted = _v(title).casefold()
    return next((m for m in CORROSION_METHODS if m.casefold() == wanted), '')


def _path(file_field):
    try:
        path = file_field.path if file_field else ''
    except (ValueError, NotImplementedError):
        return ''
    return path if path and os.path.exists(path) else ''


def drawing_sheet(path):
    """Horizontal Drawing for a landscape (or square) picture, Vertical Drawing for a portrait one."""
    try:
        with Image.open(path) as img:
            width, height = img.size
    except OSError:
        return HORIZONTAL
    return VERTICAL if height > width else HORIZONTAL


def _summary(report):
    title = f'{TITLE} {_v(report.item_description)}'.strip()
    return {
        'B2': title,
        'L5': report.client, 'L6': report.location, 'L7': report.work_order,
        'AA5': report.test_date,
        'AJ5': report.report_date or date.today(),     # the template's =TODAY() otherwise moves every day
        'AA6': report.procedure, 'AH6': report.procedure_rev,
        'AC7': report.equipment_id,
        'I8': _lines(report.weld_technician, report.weld_technician_cert),
        'AC8': _lines(report.weld_reviewer, report.weld_reviewer_cert),
        'B11': report.examination_scope,
        'B18': report.executive_summary,
        'B43': report.notes,
    }


def _setup(setup):
    method = method_name(setup.title)
    image = setup.images.order_by('order', 'pk').first()
    cells = {
        'AG2': method or setup.title,
        'J7': setup.surface_prep, 'Z7': setup.material_temp, 'AJ7': setup.tr_min, 'AN7': setup.tr_max,
        'J8': setup.inspection_material, 'Z8': setup.inspection_temp,
        'AH8': _serial(setup.scope_model, setup.scope_serial),
        'L9': _serial(' '.join(p for p in (_v(setup.cal_material), _v(setup.cal_block_type)) if p), setup.cal_block_serial),
        'AB9': _serial(setup.transducer_model, setup.transducer_serial),
    }
    return SetupPage(cells=cells, method_known=bool(method), picture=_path(image.image) if image else '')


def corrosion_pages(report):
    """Everything the corrosion form gets for this report, page by page."""
    pages = CorrosionPages(summary=_summary(report))
    pages.setups = [_setup(s) for s in report.setups.order_by('order', 'pk').prefetch_related('images')]
    for drawing in report.images.filter(kind=ReportImage.DRAWING).order_by('order', 'pk'):
        path = _path(drawing.image)
        if path:
            pages.drawings.append((drawing_sheet(path), path))
    slots = [ImageSlot(path, _v(img.caption), _v(img.description))
             for img in report.images.filter(kind=ReportImage.SCAN).order_by('order', 'pk')
             if (path := _path(img.image))]
    pages.images = [slots[i:i + 2] for i in range(0, len(slots), 2)]
    pages.summary[TOTAL_PAGES] = str(pages.page_count)
    return pages


# ── Writing them through Excel ──────────────────────────────────────────────

def fill_corrosion(wb, pages, write, add_picture):
    """
    Fills the opened template. `write(ws, cells)` and `add_picture(ws, path, box)` are the weld
    form's helpers (excel_report.py), passed in to keep this module free of its imports.
    """
    sheets = {ws.Name: ws for ws in wb.Worksheets}
    for ws in sheets.values():
        ws.Unprotect()   # the form's sheets are protected without a password

    summary = sheets[SUMMARY]
    write(summary, pages.summary)
    placed = [summary]

    def copy_after(master, name):
        count = wb.Worksheets.Count
        master.Copy(None, placed[-1])
        if wb.Worksheets.Count != count + 1:
            raise RuntimeError(f'Excel did not add the {name} page.')
        ws = wb.Worksheets(placed[-1].Index + 1)
        ws.Name = name
        placed.append(ws)
        return ws

    for i, setup in enumerate(pages.setups, start=1):
        ws = copy_after(sheets[SETUP], f'{SETUP} {i}')
        write(ws, setup.cells)
        if not setup.method_known:
            ws.Range(METHOD_DESCRIPTION).MergeArea.ClearContents()   # the lookup would show #N/A
        if setup.picture:
            add_picture(ws, setup.picture, SETUP_PICTURE)

    for i, (sheet, path) in enumerate(pages.drawings, start=1):
        ws = copy_after(sheets[sheet], f'Drawing {i}')
        add_picture(ws, path, DRAWING_PICTURE[sheet])

    for i, slots in enumerate(pages.images, start=1):
        ws = copy_after(sheets[IMAGES], f'Images {i}')
        for slot, (box, caption, description) in zip(slots, IMAGE_SLOTS):
            add_picture(ws, slot.picture, box)
            write(ws, {caption: slot.caption, description: slot.description})
        if len(slots) == 1:
            ws.Rows(SECOND_IMAGE_ROWS).Hidden = True

    for name in (SETUP, HORIZONTAL, VERTICAL, THICKNESS, IMAGES):
        sheets[name].Delete()
    sheets[FORMULAS].Visible = XL_SHEET_HIDDEN
    if len(pages.setups) == 1:
        placed[1].Name = SETUP   # the master's name is free now

    for page, ws in enumerate(placed, start=1):
        ws.PageSetup.RightFooter = FOOTER.format(page=page, total=len(placed))
        ws.Protect()
    summary.Activate()
