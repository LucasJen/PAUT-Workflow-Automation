"""
The inventory to and from Excel: Export (every equipment library as one workbook, for audits) and
Import from workbook (the weld report workbook's Scope and Encoder and All Probes sheets, as
manage.py import_inventory does: checked first, then saved).
"""
import os
import uuid
import zipfile
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .export import inventory_workbook
from .inventory import InventoryError, apply_inventory, read_probes, read_scopes
from .models import Probe, Scope

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
SESSION_KEY = 'inventory_import'


def export_inventory(request):
    response = HttpResponse(inventory_workbook(), content_type=XLSX)
    response['Content-Disposition'] = f'attachment; filename="Equipment inventory {date.today():%Y-%m-%d}.xlsx"'
    return response


def _upload_dir():
    return Path(settings.REPORT_OUTPUT_DIR or Path(settings.BASE_DIR) / 'outputs') / 'tmp'


def _read(path):
    """(scopes, probes, problems): each sheet read on its own, so a workbook with only one still imports."""
    if not zipfile.is_zipfile(path):
        return [], [], ['The file could not be read as an Excel workbook (.xlsx).']
    found, problems = {}, []
    for kind, reader in (('scopes', read_scopes), ('probes', read_probes)):
        try:
            found[kind] = reader(path)
        except InventoryError as e:
            found[kind] = []
            problems.append(str(e))
        except Exception as e:   # a damaged workbook
            found[kind] = []
            problems.append(f'The file could not be read as an Excel workbook ({e}).')
    return found['scopes'], found['probes'], list(dict.fromkeys(problems))


def _marked(items, model):
    """Each item with 'exists': whether the inventory already has its serial number (it's then updated)."""
    serials = {s.strip() for s in model.objects.values_list('serial_number', flat=True) if s.strip()}
    return [{**item, 'exists': item['serial_number'].strip() in serials} for item in items]


def import_inventory(request):
    """GET: the upload form. POST check: reads the workbook and shows what it would add / update. POST import: saves it."""
    pending = request.session.get(SESSION_KEY)
    if request.method == 'POST' and 'check' in request.POST:
        upload = request.FILES.get('workbook')
        if upload is None or not upload.name.lower().endswith(('.xlsx', '.xlsm')):
            messages.error(request, 'Choose the weld report workbook (.xlsx) to import from.')
            return redirect('import-inventory')
        folder = _upload_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'inventory-{uuid.uuid4().hex}.xlsx'
        with open(path, 'wb') as f:
            for chunk in upload.chunks():
                f.write(chunk)
        _discard(pending)
        request.session[SESSION_KEY] = {'path': str(path), 'name': upload.name}
        return redirect('import-inventory')
    if request.method == 'POST' and 'import' in request.POST and pending:
        scopes, probes, _ = _read(pending['path'])
        counts = apply_inventory(scopes, probes)
        _discard(pending)
        request.session.pop(SESSION_KEY, None)
        messages.success(request, 'Imported: ' + ', '.join(f'{n} {what}' for what, n in counts.items() if n) + '.'
                         if any(counts.values()) else 'Nothing to import.')
        return redirect('scope-list')
    if request.method == 'POST' and 'cancel' in request.POST:
        _discard(pending)
        request.session.pop(SESSION_KEY, None)
        return redirect('import-inventory')

    context = {}
    if pending and os.path.exists(pending['path']):
        scopes, probes, problems = _read(pending['path'])
        context = {'name': pending['name'], 'scopes': _marked(scopes, Scope), 'probes': _marked(probes, Probe),
                   'problems': problems, 'total': len(scopes) + len(probes)}
    return render(request, 'equipment/import_inventory.html', context)


def _discard(pending):
    if pending:
        try:
            os.remove(pending['path'])
        except OSError:
            pass
