"""
Guided Creation from an existing Short Form: an .xlsx of the corrosion form (598-PAUTFORM-009,
filled by hand or made by this app) read back into a new Short Form report - the Summary page
(title, client, dates, procedure, people, examination scope, summary of results, notes), each
Setup Information page (method, its description, material, temperatures, thickness range,
instrument, calibration block and probe, and the pictures in its picture area), the drawing pages'
pictures, the Thickness Table's rows and every picture on the Images pages with its caption and
description.

read_short_form() reads the workbook (no Excel: xlsx_reader.py) into plain values from the cell
map the Excel output writes with (corrosion_report.py); build_short_form() makes the report.
"""
import re
from datetime import date, datetime
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction

from ..models import Report, ReportImage, ResultsRow, ResultsTable, Setup, SetupImage, TextSnippet
from ..report_types import get_report_type
from .corrosion_report import (
    HORIZONTAL, IMAGES, SETUP, SUMMARY, THICKNESS, THICKNESS_COLUMNS, THICKNESS_TABLE_FIRST_ROW, VERTICAL,
)
from .weld_report_import import _composite, _parse_date
from .xlsx_reader import XlsxError, read_workbook, split_ref

CORROSION_TYPE = 'paut_corrosion'

# Summary page (corrosion_report._summary)
SUMMARY_CELLS = {
    'item_description': 'B2', 'client': 'L5', 'location': 'L6', 'work_order': 'L7',
    'procedure': 'AA6', 'procedure_rev': 'AH6', 'equipment_id': 'AC7',
}
DATE_CELLS = {'test_date': 'AA5', 'report_date': 'AJ5'}
PEOPLE_CELLS = {('weld_technician', 'weld_technician_cert'): 'I8', ('weld_reviewer', 'weld_reviewer_cert'): 'AC8'}
# The text boxes under their headings (where they sit moves a little between the form's copies)
BOXES = {'examination_scope': 'examination scope', 'executive_summary': 'summary of results', 'notes': 'notes'}
# Setup Information page (corrosion_report._setup)
SETUP_CELLS = {
    'title': 'AG2', 'surface_prep': 'J7', 'material_temp': 'Z7', 'tr_min': 'AJ7', 'tr_max': 'AN7',
    'inspection_material': 'J8', 'inspection_temp': 'Z8',
}
DESCRIPTION_CELL = 'B5'
SERIAL_CELLS = {'scope': 'AH8', 'cal_block': 'L9', 'transducer': 'AB9'}
SETUP_PICTURE_ROWS = (10, 44)                      # SETUP_PICTURE B10:AO44
DRAWING_PAGES = re.compile(rf'^(?:{HORIZONTAL}|{VERTICAL}|Drawing)\b', re.I)
# A serial number's marker as typed: 'SN: ', 'Sn:', 'SN#: ', 'S# ', 'Serial No.'
SERIAL = re.compile(r'\s*/?\s*(?:\bS/?N\s*#?|\bS#|\bSerial(?: No\.?| Number)?)\s*[:.]?\s*', re.I)
# ...or none: the serial on its own line, or after ' / ' ('Carbon Steel / 51349')
BARE_SERIAL = re.compile(r'^(.*\S)\s*(?:\n|\s/)\s*([A-Z0-9][\w-]*\d[\w-]*)\s*$', re.I | re.S)
# A calibration block's type, after its material ('Carbon Steel Mini PACS', 'Stainless IIW', 'Carbon Steel 10-Step')
BLOCK_TYPE = re.compile(r'(?:\b\d+[ -]?step|\b(?:mini[ -]?pacs|pacs|iiw|dsc|navships?|step (?:wedge|block)|ascb|asme'
                        r'|basic cal|aut cal|calibration block|cal block|sdh|nozzle|block))\b.*$', re.I)
THICKNESS_END = re.compile(r'^\s*(?:low readings|total)', re.I)
RESULTS_HEADING = re.compile(r'note|result|comment', re.I)
# A word each of the form's own Thickness Table headings has ('Minimum Thickness (inches)', 'Min. Thickness')
HEADING_WORDS = ('scan', 'axial', 'circ', 'min', 'av', 'result')


class ShortFormError(Exception):
    """The file isn't a Short Form this can read."""


def _na(text):
    return text.strip().upper() in ('N/A', 'NA', 'N / A')


# ── Reading the workbook ───────────────────────────────────────────────────

def _summary_sheet(sheets):
    if SUMMARY in sheets:
        return sheets[SUMMARY]
    for sheet in sheets.values():
        if sheet.find(r'^\s*examination scope\s*$') and sheet.find(r'client company'):
            return sheet
    return None


def _check_layout(sheet):
    expected = {'B5': 'client company', 'V5': 'test date', 'B6': 'location', 'B7': 'work order', 'V7': 'unit'}
    wrong = [ref for ref, label in expected.items() if label not in sheet.text(ref).lower()]
    if len(wrong) > 1:
        raise ShortFormError(
            "This isn't laid out like the Short Form (598-PAUTFORM-009): its Summary labels aren't where the form "
            f"has them ({', '.join(wrong)}).")


def _date(sheet, ref):
    value = sheet.get(ref)
    if isinstance(value, datetime):
        return value.date().isoformat()
    return _parse_date(sheet.text(ref).split(' ')[0]) if sheet.text(ref) else ''


def _person(text):
    """
    'Lucas Jennings\\nUltrasonics Level II', 'Lucas Jennings /\\nPAUT Level II' or 'Sky Tervo / PAUT Lvl II'
    -> (name, certification); anything else stays the name ('Sky Tervo PAUT Lvl II, Daire Butturff ...').
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2:
        return lines[0].rstrip('/ ').strip(), ' '.join(lines[1:])
    parts = text.split(' / ')
    if len(parts) == 2 and all(p.strip() for p in parts):
        return parts[0].strip(), parts[1].strip()
    return text.strip(), ''


def _box(sheet, heading):
    """The text under a heading of the Summary page (its next filled cell in column B)."""
    for ref in sheet.find(rf'^\s*{heading}\s*:?\s*$'):
        col, row = split_ref(ref)
        for below in range(row + 1, row + 4):
            text = sheet.text(f'{col}{below}')
            if text:
                return text
        return ''
    return ''


def _summary(sheet):
    values = {name: sheet.text(ref) for name, ref in SUMMARY_CELLS.items()}
    if not values['procedure_rev']:   # typed in one cell: '100-UT-020 Rev. 9.0'
        match = re.match(r'(.*?)[\s,]+rev(?:ision)?\.?\s*(\S.*)$', values['procedure'], re.I)
        if match:
            values['procedure'], values['procedure_rev'] = match.group(1).strip(), match.group(2).strip()
    for name, ref in DATE_CELLS.items():
        values[name] = _date(sheet, ref)
    for names, ref in PEOPLE_CELLS.items():
        values.update(zip(names, _person(sheet.text(ref))))
    for name, heading in BOXES.items():
        values[name] = _box(sheet, heading)
    return values


def split_serial(text):
    """'Olympus X3-64\\nSn:QC-0082535' -> ('Olympus X3-64', 'QC-0082535'); no serial -> (text, '')."""
    text = text.strip()
    parts = SERIAL.split(text, maxsplit=1)
    if len(parts) < 2:
        bare = BARE_SERIAL.match(text)
        parts = [bare.group(1), bare.group(2)] if bare else [text]
    model = ' '.join(parts[0].split()).rstrip('/ ').strip()
    return model, (' '.join(parts[1].split()) if len(parts) > 1 else '')


def split_block(text):
    """'Carbon Steel Mini PACS' -> ('Carbon Steel', 'Mini PACS'); printed together, so nothing's lost."""
    match = BLOCK_TYPE.search(text)
    if not match or match.start() == 0:
        return text, ''
    return text[:match.start()].strip(), match.group().strip()


def _filled(values):
    return any(v and not _na(v) for v in values.values())


def _setup_pages(sheets):
    pages = []
    for name, sheet in sheets.items():
        if sheet.hidden or not name.lower().startswith(SETUP.lower()):
            continue
        values = {field: sheet.text(ref) for field, ref in SETUP_CELLS.items()}
        values['scope_model'], values['scope_serial'] = split_serial(sheet.text(SERIAL_CELLS['scope']))
        block, values['cal_block_serial'] = split_serial(sheet.text(SERIAL_CELLS['cal_block']))
        values['cal_material'], values['cal_block_type'] = split_block(block)
        values['transducer_model'], values['transducer_serial'] = split_serial(sheet.text(SERIAL_CELLS['transducer']))
        description = sheet.text(DESCRIPTION_CELL)
        area = [p for p in sheet.pictures if SETUP_PICTURE_ROWS[0] <= p.row <= SETUP_PICTURE_ROWS[1]]
        if not _filled(values) and not description and not area:
            continue   # the blank master page
        picture, ext = _composite(area) if area else (None, None)
        pages.append({'sheet': name, 'values': values, 'description': description,
                      'picture': picture, 'ext': ext, 'unreadable': bool(area) and picture is None})
    return pages


def _drawing_pages(sheets):
    pages = []
    for name, sheet in sheets.items():
        if sheet.hidden or not DRAWING_PAGES.match(name) or not sheet.pictures:
            continue
        picture, ext = _composite(sheet.pictures)
        pages.append({'sheet': name, 'picture': picture, 'ext': ext, 'unreadable': picture is None})
    return pages


def _thickness_rows(sheets):
    """(headings, rows) of the Thickness Table: rows of the form's six cells as typed, results last."""
    sheet = next((s for name, s in sheets.items() if not s.hidden
                  and name.lower() in (THICKNESS.lower(), 'thickness')), None)
    if sheet is None:
        return [], []
    header = THICKNESS_TABLE_FIRST_ROW - 1
    headings = [sheet.text(f'{col}{header}') for col in THICKNESS_COLUMNS]
    # A hand-made table may have fewer columns, its notes not in the last one (Weld ID ... Notes)
    order = list(range(len(THICKNESS_COLUMNS)))
    last = max((i for i, h in enumerate(headings) if h), default=len(headings) - 1)
    if last < len(headings) - 1 and RESULTS_HEADING.search(headings[last]):
        order[last], order[-1] = order[-1], order[last]
    rows = []
    max_row = max((split_ref(ref)[1] for ref in sheet.cells), default=0)
    for row in range(THICKNESS_TABLE_FIRST_ROW, max_row + 1):
        if THICKNESS_END.match(sheet.text(f'B{row}')):
            break
        typed = [sheet.text(f'{col}{row}') for col in THICKNESS_COLUMNS]
        if any(typed):
            rows.append([typed[i] for i in order])
    return [headings[i] for i in order], rows


def _image_pages(sheets):
    """
    [{'sheet', 'caption', 'description', 'picture', 'ext', 'unreadable'}]: each caption (column B)
    with the pictures above it, back to the caption before (hand-made pages carry on past two slots,
    not always on the form's 24-row step).
    """
    slots = []
    for name, sheet in sheets.items():
        if sheet.hidden or not name.lower().startswith(IMAGES.lower()):
            continue
        captions = sorted({split_ref(ref)[1] for ref in sheet.cells
                           if split_ref(ref)[0] == 'B' and sheet.text(ref) and split_ref(ref)[1] > 2})
        pictures = sorted(sheet.pictures, key=lambda p: (p.row, p.col))
        previous = 0
        for row in captions + [None]:
            area = [p for p in pictures if p.row > previous and (row is None or p.row <= row)]
            caption = sheet.text(f'B{row}') if row else ''
            description = sheet.text(f'K{row}') if row else ''
            previous = row or previous
            if not area:
                if caption and not _na(caption):
                    slots.append({'sheet': name, 'caption': caption, 'description': description,
                                  'picture': None, 'ext': None, 'unreadable': False})
                continue
            picture, ext = _composite(area)
            slots.append({'sheet': name, 'caption': '' if _na(caption) else caption,
                          'description': '' if _na(description) else description,
                          'picture': picture, 'ext': ext, 'unreadable': picture is None})
    return slots


KNOWN_SHEETS = re.compile(rf'^(?:{SUMMARY}|{SETUP}|{HORIZONTAL}|{VERTICAL}|Drawing|{THICKNESS}|Thickness|{IMAGES}'
                          r'|Formulas)\b', re.I)


def read_short_form(fileobj, filename=''):
    """
    Everything on a Short Form workbook as plain values:
    {'filename', 'report': {field: text}, 'setups': [...], 'drawings': [...], 'headings': [...],
     'rows': [[cell, ...]], 'images': [...], 'notes': [...]}. Raises ShortFormError.
    """
    try:
        sheets = read_workbook(fileobj)
    except XlsxError as e:
        raise ShortFormError(str(e)) from e
    summary = _summary_sheet(sheets)
    if summary is None:
        raise ShortFormError("This workbook has no Short Form Summary page (a sheet with the form's Client Company and "
                             'Examination Scope). Weld reports and other forms can\'t be read here.')
    _check_layout(summary)
    headings, rows = _thickness_rows(sheets)
    data = {
        'filename': filename,
        'report': _summary(summary),
        'setups': _setup_pages(sheets),
        'drawings': _drawing_pages(sheets),
        'headings': headings,
        'rows': rows,
        'images': _image_pages(sheets),
        'notes': [],
    }
    form = [h for _, h in get_report_type(CORROSION_TYPE).results_columns]
    if rows and not all(word in _plain(h) for word, h in zip(HEADING_WORDS, headings)):
        data['notes'].append(f"The file's Thickness Table has its own headings ({', '.join(h for h in headings if h)}); "
                             f"its rows went into the form's columns ({', '.join(form)}) in that order.")
    others = [name for name, sheet in sheets.items() if not sheet.hidden and not KNOWN_SHEETS.match(name)]
    if others:
        data['notes'].append(f"{', '.join(others)} {'isn' if len(others) == 1 else 'aren'}'t part of the form; "
                             'left out.')
    return data


def _plain(text):
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


# ── Building the report ────────────────────────────────────────────────────

def _set_values(obj, values, notes, where):
    for name, value in values.items():
        if value in (None, '') or not hasattr(obj, name):
            continue
        field = obj._meta.get_field(name)
        limit = getattr(field, 'max_length', None)
        if limit and isinstance(value, str) and len(value) > limit and field.get_internal_type() == 'CharField':
            notes.append(f"{where}: the {field.verbose_name} was longer than the app's field holds "
                         f'({limit} characters); check its end.')
            value = value[:limit]
        setattr(obj, name, value)


def method_snippet(text, method, filename, notes):
    """
    The Text library technique description a setup page's description is ('<title> – <body>' as
    printed); when none is, it's added to the library so it prints the same.
    """
    if not text.strip():
        return None
    wanted = _plain(text)
    snippets = list(TextSnippet.objects.filter(kind=TextSnippet.TECHNIQUE))
    for snippet in snippets:
        if _plain(f'{snippet.title} {snippet.body}') == wanted or _plain(snippet.body) == wanted:
            return snippet
    match = re.match(r'^(.{1,200}?)\s+[–—-]\s+(.+)$', text.strip(), re.S)
    title, body = (match.group(1).strip(), match.group(2).strip()) if match else ('', text.strip())
    base = (title or method or 'Imported method')[:80]
    names = {s.name.lower() for s in snippets}
    name, n = f'{base} ({Path(filename).stem or "imported"})'[:100], 2
    while name.lower() in names:
        name, n = f'{base} ({Path(filename).stem or "imported"} {n})'[:100], n + 1
    snippet = TextSnippet.objects.create(kind=TextSnippet.TECHNIQUE, name=name, title=title, body=body)
    notes.append(f"The method description '{title or text[:40]}' wasn't in the Text library; it was added as '{name}'.")
    return snippet


def _save_picture(image, field, name, item):
    field.save(f'{name}.{item["ext"]}', ContentFile(item['picture']), save=False)
    image.save()


@transaction.atomic
def build_short_form(data, defaults=None, job_folder=''):
    """The Short Form for read_short_form()'s values, over a defaults set's values for what the file
    leaves blank. Returns (report, notes)."""
    from .corrosion_import import FK_FIELDS, SETUP_FIELDS
    from .job_import import _set_report_values
    notes = list(data.get('notes') or [])
    values = dict(data['report'])

    report = Report(report_type=CORROSION_TYPE, report_date=date.today())
    if defaults is not None:
        _set_report_values(report, defaults.report_values)
    for name in DATE_CELLS:
        when = values.pop(name, '')
        if when:
            setattr(report, name, date.fromisoformat(when))
    _set_values(report, values, notes, 'Summary')
    for name, second in (('weld_technician', 'weld_technician_cert'), ('weld_reviewer', 'weld_reviewer_cert'),
                         ('procedure', 'procedure_rev')):
        if values.get(name):   # the file's, not a defaults set's, beside the file's name
            setattr(report, second, values.get(second, ''))
    if not report.document_filename:
        report.document_filename = (Path(job_folder).name if job_folder else Path(data.get('filename') or '').stem)[:200]
    report.job_folder = str(job_folder or '')
    report.save()

    setup_defaults = (defaults.setup_values or {}) if defaults is not None else {}
    pages = data['setups'] or [{'sheet': SETUP, 'values': {}, 'description': '', 'picture': None}]
    if not data['setups']:
        notes.append('The file has no filled Setup Information page: one empty setup was added; fill in its method '
                     'and equipment.')
    for order, page in enumerate(pages):
        setup = Setup(report=report, order=order)
        for name, value in setup_defaults.items():
            if name not in SETUP_FIELDS:
                continue
            if name in FK_FIELDS:
                setattr(setup, f'{name}_id', int(value) if str(value).isdigit() else None)
            else:
                setattr(setup, name, value)
        _set_values(setup, {k: v for k, v in page['values'].items() if not _na(v)}, notes, page['sheet'])
        if page['description']:
            setup.method_description = method_snippet(page['description'], setup.title, data.get('filename') or '', notes)
        setup.save()
        if page.get('picture'):   # printed when the setup has no .nde sheet (an imported one never has)
            image = SetupImage(setup=setup, order=0)
            _save_picture(image, image.image, f'imported_{report.pk}_setup{order}', page)

    order = 0
    for page in data['drawings']:
        if page['picture']:
            image = ReportImage(report=report, kind=ReportImage.DRAWING, order=order)
            _save_picture(image, image.image, f'imported_{report.pk}_drawing{order}', page)
            order += 1
    for slot in data['images']:
        if slot['picture']:
            image = ReportImage(report=report, kind=ReportImage.SCAN, order=order,
                                caption=slot['caption'][:200], description=slot['description'])
            _save_picture(image, image.image, f'imported_{report.pk}_image{order}', slot)
            order += 1

    if data['rows']:
        headings = get_report_type(CORROSION_TYPE).results_headings
        table = ResultsTable.objects.create(report=report, columns=headings)
        ResultsRow.objects.bulk_create(ResultsRow(table=table, order=i, cells=list(cells))
                                       for i, cells in enumerate(data['rows']))

    unreadable = [item['sheet'] for item in data['setups'] + data['drawings'] + data['images'] if item.get('unreadable')]
    if unreadable:
        notes.append(f"A picture on {', '.join(dict.fromkeys(unreadable))} couldn't be read (a drawing format this "
                     "can't open); add it again in the editor.")
    missing = [slot['caption'] for slot in data['images'] if not slot['picture'] and not slot['unreadable']]
    if missing:
        notes.append(f"No picture went with the Images caption{'s' if len(missing) != 1 else ''} "
                     f"{', '.join(repr(c) for c in missing)}; left out.")
    return report, notes


def import_short_form(fileobj, filename='', defaults=None, job_folder=''):
    """read_short_form() then build_short_form(): (report, notes, data)."""
    data = read_short_form(fileobj, filename)
    report, notes = build_short_form(data, defaults, job_folder)
    return report, notes, data
