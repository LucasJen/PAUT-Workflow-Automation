"""
Renders a Report into a Word document with docxtpl (Jinja tags inside the .docx).

The report type (reports/report_types.py) picks the template in word_templates/. Templates
use {{ var }}, {%p for ... %} (paragraph loops) and {%tr for ... %} (table-row loops); the
variables they can use are built by build_context() below and listed in
word_templates/TEMPLATE_TAGS.md.
"""
import io
import os
import re

from django.conf import settings
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from docxtpl import DocxTemplate, InlineImage, Listing, RichText

from ..models import ReportImage
from ..report_types import SECTIONS, get_report_type
from ..results import report_results, report_scan_rows

FULL_WIDTH = Inches(7.0)       # drawings, scan images
HALF_WIDTH = Inches(3.45)      # calibration screenshots, two per line
NUMBER = re.compile(r'^-?\d+(\.\d+)?$')


# ── Value formatting ─────────────────────────────────────────────────────

def with_unit(value, unit):
    """'0.500' -> '0.500"'; values that already carry a unit (or text like 'N/A') are left alone."""
    value = (value or '').strip()
    return f'{value}{unit}' if NUMBER.match(value) else value


def prose(text):
    """Multi-line text for the template: blank lines start new paragraphs, single newlines break lines."""
    text = (text or '').strip().replace('\r\n', '\n')
    return Listing(re.sub(r'\n\s*\n', '\a', text)) if text else ''


def long_date(d):
    return f'{d.day} {d:%B}, {d.year}' if d else ''


def short_date(d):
    return f'{d.month}/{d.day}/{d.year}' if d else ''


def date_range(start, end):
    """'8/13/2026 – 8/25/2026', or a single date when there is no (different) end date."""
    if start and end and end != start:
        return f'{short_date(start)} – {short_date(end)}'
    return short_date(start or end)


def wave_mode(value):
    return f'{value} Wave' if value in ('Longitudinal', 'Shear') else (value or '')


def lines(text):
    return [line.strip() for line in re.split(r'[\n;]', text or '') if line.strip()]


# ── Context ──────────────────────────────────────────────────────────────

def _image(tpl, image_field, width):
    try:
        path = image_field.path
    except (ValueError, NotImplementedError):
        return None
    return InlineImage(tpl, path, width=width) if os.path.exists(path) else None


def _setup_context(setup, number, report, tpl):
    images = [_image(tpl, i.image, HALF_WIDTH) for i in setup.images.all()]
    return {
        'title': setup.title or setup.beam_formation or setup.transducer_model or f'Setup {number}',
        'equipment_type': setup.scope_platform or setup.manufacturer,
        'scope_model': setup.scope_model,
        'scope_serial': setup.scope_serial,
        'x_res': with_unit(setup.x_res, '"'),
        'y_res': with_unit(setup.y_res, '"'),
        'transducer_model': setup.transducer_model,
        'transducer_serial': setup.transducer_serial,
        'foc_depth': with_unit(setup.foc_depth, '"'),
        'wave_mode': wave_mode(setup.wave_propagation),
        'freq': setup.freq,
        'elements': setup.elements,
        'cal_material': setup.cal_material,
        'material_temp': with_unit(setup.material_temp, '°F'),
        'cal_block': ' S/N: '.join(v for v in (setup.cal_block_type, setup.cal_block_serial) if v),
        'surface_prep': setup.surface_prep,
        'tr_min': with_unit(setup.tr_min, '"'),
        'tr_max': with_unit(setup.tr_max, '"'),
        'procedure': setup.procedure or ', '.join(lines(report.procedure)),
        'images': [i for i in images if i],
    }


# Fallback keys for report types without fixed results columns (mapped by position)
DEFAULT_RESULT_KEYS = ('scan_id', 'orientation', 'x_range', 'y_range', 'avg_thk', 'min_thk', 'comments')


def _scans(report):
    """Results rows keyed by the report type's column keys (r.scan_id, r.min_thk, r.comments, ...)."""
    columns, rows = report_results(report)
    if not columns:
        return []
    keys = [key for key, _ in get_report_type(report.report_type).results_columns] or list(DEFAULT_RESULT_KEYS)
    scans = []
    for cells in rows:
        cells = list(cells) + [''] * len(keys)
        row = dict(zip(keys, cells))
        for key in DEFAULT_RESULT_KEYS:
            row.setdefault(key, '')
        scans.append(row)

    # Highlight the thinnest reading in the table
    readings = [float(s['min_thk']) for s in scans if NUMBER.match((s['min_thk'] or '').strip())]
    thinnest = min(readings) if readings else None
    for s in scans:
        value = (s['min_thk'] or '').strip()
        s['min_thk'] = value
        s['is_min'] = bool(thinnest is not None and NUMBER.match(value) and float(value) == thinnest)
        s['comments'] = prose(s['comments'])
        s['image'] = None
    return scans


def _people(people, role):
    return [{'name': p.name, 'certification': p.certification} for p in people if getattr(p, role)]


def _drawings(report, tpl):
    """Equipment drawings: one titled figure each, under the Drawing heading."""
    figures = []
    for image in report.images.filter(kind=ReportImage.DRAWING).order_by('order'):
        inline = _image(tpl, image.image, FULL_WIDTH)
        if inline:
            figures.append({'title': image.caption, 'images': [inline]})
    return figures


def _scan_images(report, tpl):
    """
    Photo-summary blocks (image + Scan ID + comments), in results-table order. Each image's
    comments come from the results row with the same Scan ID; images not tied to a row follow,
    labelled with their own label.
    """
    images = [i for i in report.images.filter(kind=ReportImage.SCAN).order_by('order')]
    blocks, used = [], set()
    for scan_id, comments in report_scan_rows(report):
        for image in images:
            if image.pk not in used and image.scan_id == scan_id:
                used.add(image.pk)
                inline = _image(tpl, image.image, FULL_WIDTH)
                if inline:
                    blocks.append({'scan_id': scan_id, 'comments': prose(comments), 'image': inline})
    for image in images:
        if image.pk not in used:
            inline = _image(tpl, image.image, FULL_WIDTH)
            if inline:
                blocks.append({'scan_id': image.caption or image.scan_id, 'comments': '', 'image': inline})
    return blocks


def build_context(report, tpl):
    report_type = get_report_type(report.report_type)
    setup_objects = list(report.setups.order_by('order').prefetch_related('images'))
    setups = [_setup_context(s, i + 1, report, tpl) for i, s in enumerate(setup_objects)]
    # Cover "Procedures": each setup's procedure once, in order; else the report's procedure lines
    procedures = list(dict.fromkeys(s.procedure.strip() for s in setup_objects if s.procedure.strip()))
    procedures = procedures or lines(report.procedure)
    people = list(report.people.all())
    scans = _scans(report)
    drawings = _drawings(report, tpl)
    scan_images = _scan_images(report, tpl)

    return {
        'client': report.client,
        'location': report.location,
        'document_title': report.document_title,
        'document_title_upper': (report.document_title or '').upper(),
        'report_date_long': long_date(report.report_date),
        'test_dates': date_range(report.test_date, report.test_end_date),
        'project_number': report.project_number or 'N/A',
        'work_order': report.work_order,
        'project_type': report.project_type,
        'procedures': procedures,
        'prepared_by': _people(people, 'prepared'),
        'examined_by': _people(people, 'examined'),
        'reviewed_by': _people(people, 'reviewed'),
        'examination_scope': prose(report.examination_scope),
        'executive_summary': prose(report.executive_summary),
        'equipment_id': report.equipment_id,
        'asset_description': '',
        'access': prose(report.equipment_overview),
        'work_scope': prose(report.work_scope),
        'x_axis_reference': report.x_axis_reference,
        'y_axis_reference': report.y_axis_reference,
        'techniques': [{'text': RichText(t)} for t in lines(report.ut_method)],
        'setups': setups,
        'results_title': f"PAUT {setups[0]['title']} Work Scope" if setups else 'PAUT Work Scope',
        'scans': scans,
        'scan_images': scan_images,
        'figures': {'drawings': drawings},
        # Section blocks in the master template print only for the report type's sections
        'show': {key: key in report_type.sections for key in SECTIONS},
    }


# ── Rendering ────────────────────────────────────────────────────────────

def _fill_empty_cells(docx):
    """
    Word treats a table cell without a paragraph as a corrupt file (python-docx doesn't mind).
    A cell whose content was only a loop (e.g. the cover's Procedures with none listed) ends
    up empty, so give every such cell an empty paragraph.
    """
    parts = [docx.element]
    for section in docx.sections:
        for hf in (section.header, section.footer, section.first_page_header, section.first_page_footer,
                   section.even_page_header, section.even_page_footer):
            if not hf.is_linked_to_previous:
                parts.append(hf._element)
    for part in parts:
        for tc in part.iter(qn('w:tc')):
            if tc.find(qn('w:p')) is None:
                tc.append(OxmlElement('w:p'))


def _update_fields_on_open(docx):
    """Ask Word to refresh the TOC, page count, page numbers and cross-references when opened."""
    settings_el = docx.settings.element
    existing = settings_el.find(qn('w:updateFields'))
    if existing is None:
        existing = OxmlElement('w:updateFields')
        settings_el.append(existing)
    existing.set(qn('w:val'), 'true')


def template_path(report):
    return os.path.join(settings.BASE_DIR, 'word_templates', get_report_type(report.report_type).template)


def render_report(report, update_fields_on_open=True):
    """
    The finished report as .docx bytes. update_fields_on_open asks Word to refresh fields when a
    person opens the file; the Word PDF export updates fields itself, so it turns this off
    (the prompt could otherwise stall the hidden Word instance).
    """
    tpl = DocxTemplate(template_path(report))
    tpl.render(build_context(report, tpl), autoescape=True)
    _fill_empty_cells(tpl.docx)
    if update_fields_on_open:
        _update_fields_on_open(tpl.docx)
    buffer = io.BytesIO()
    tpl.save(buffer)
    return buffer.getvalue()
