"""
What the assistant can read: each report, setup and library document as labelled plain text, with
a short label and a link to open it in the app. The search index (index.py) and the tools
(tools.py) both use these.
"""
import os
from urllib.parse import urlencode

from django.urls import reverse

from documents.models import Document
from reports.models import Report, Setup
from reports.report_types import get_report_type
from reports.results import report_results

REPORT, SETUP, DOCUMENT = 'report', 'setup', 'document'
# Internal fields that mean nothing to a reader
SKIP_FIELDS = {'id', 'report', 'order', 'updated_at', 'nde_sheet', 'job_folder_files', 'report_type',
               'api_key_encrypted'}


def _value(obj, field):
    value = getattr(obj, field.name)
    if value in (None, '') or value is False:
        return ''
    if value is True:
        return 'Yes'
    return str(value).strip()


def labelled_fields(obj):
    """'Label: value' lines for an object's filled-in fields."""
    lines = []
    for field in obj._meta.concrete_fields:
        if field.name in SKIP_FIELDS:
            continue
        value = _value(obj, field)
        if value:
            label = str(field.verbose_name)
            lines.append(f'{label[:1].upper()}{label[1:]}: {value}')
    return lines


# ── Reports ──────────────────────────────────────────────────────────────────

def report_label(report):
    name = report.document_filename or report.document_title or report.equipment_id or 'Untitled'
    return f'Report #{report.pk} · {name}'


def report_url(report):
    return f"{reverse('create-report')}?{urlencode({'loaded': report.pk})}"


def report_text(report):
    rtype = get_report_type(report.report_type)
    lines = [report_label(report), f'Report type: {rtype.label}', *labelled_fields(report)]
    people = list(report.people.all())
    if people:
        lines.append('People: ' + '; '.join(
            ', '.join(filter(None, [p.name, p.certification, *(role for role, held in (
                ('prepared', p.prepared), ('examined', p.examined), ('reviewed', p.reviewed)) if held)]))
            for p in people))
    columns, rows = report_results(report)
    if rows:
        lines.append(f'Results table ({len(rows)} rows; columns: {" | ".join(columns)}):')
        lines += [' | '.join(str(c) for c in row) for row in rows]
    for setup in report.setups.order_by('order', 'pk'):
        lines.append(f'Setup #{setup.pk}: ' + _setup_summary(setup))
    captions = [i.caption for i in report.images.all() if i.caption]
    if captions:
        lines.append('Images: ' + '; '.join(captions))
    return '\n'.join(lines)


# ── Setups ───────────────────────────────────────────────────────────────────

def setup_label(setup):
    name = ' · '.join(filter(None, [setup.title, setup.transducer_model, setup.angle_range]))
    where = f' (report #{setup.report_id})' if setup.report_id else ' (saved setup)'
    return f'Setup #{setup.pk} · {name or "untitled"}{where}'


def setup_url(setup):
    return report_url(setup.report) if setup.report_id else reverse('edit-setup', args=[setup.pk])


def _setup_summary(setup):
    parts = [setup.title, setup.scope_model, setup.transducer_model, setup.wedge_model, setup.beam_formation,
             setup.angle_range, setup.source_file]
    return ', '.join(p for p in parts if p) or 'no details'


def setup_text(setup):
    return '\n'.join([setup_label(setup), *labelled_fields(setup)])


# ── Library documents ────────────────────────────────────────────────────────

def document_label(document):
    return ' · '.join(filter(None, [document.title, document.description])) or document.filename


def document_url(document):
    return reverse('open-document', args=[document.pk])


def document_header(document):
    lines = [f'Document #{document.pk} · {document_label(document)}',
             f'Library: {document.get_category_display()}', f'File: {document.filename}']
    if document.notes:
        lines.append(f'Notes: {document.notes}')
    return '\n'.join(lines)


def document_signature(document):
    """Changes when the file is replaced (name, size, modified time)."""
    try:
        stat = os.stat(document.file.path)
        return f'{document.file.name}:{stat.st_size}:{int(stat.st_mtime)}'
    except (OSError, ValueError, NotImplementedError):
        return document.file.name


def pdf_pages(document):
    """The PDF's text, page by page (empty pages kept, so page numbers stay right); [] for other files."""
    if document.file_type != 'pdf':
        return []
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(document.file.path)
    except Exception:
        return []
    try:
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            pages.append(textpage.get_text_range().replace('\r\n', '\n').strip())
            textpage.close()
            page.close()
        return pages
    except Exception:
        return []
    finally:
        pdf.close()


def link(kind, obj):
    """{'label', 'url'} for a source the answer used."""
    if kind == REPORT:
        return {'label': report_label(obj), 'url': report_url(obj)}
    if kind == SETUP:
        return {'label': setup_label(obj), 'url': setup_url(obj)}
    return {'label': document_label(obj), 'url': document_url(obj)}


def get(kind, pk):
    model = {REPORT: Report, SETUP: Setup, DOCUMENT: Document}[kind]
    return model.objects.filter(pk=pk).first()
