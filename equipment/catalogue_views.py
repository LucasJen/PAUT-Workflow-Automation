"""Probe and wedge catalogues: list, edit, and import from instrument files."""
import json

from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CatalogueImportForm, ProbeModelForm, WedgeModelForm
from .importers import CatalogueImportError, apply_catalogue, read_catalogue_file
from .models import ProbeModel, WedgeModel

CATALOGUES = {
    'probe': {'model': ProbeModel, 'form': ProbeModelForm, 'list': 'probe-model-list', 'edit': 'edit-probe-model',
              'noun': 'probe model', 'template': 'equipment/edit_probe_model.html'},
    'wedge': {'model': WedgeModel, 'form': WedgeModelForm, 'list': 'wedge-model-list', 'edit': 'edit-wedge-model',
              'noun': 'wedge model', 'template': 'equipment/edit_wedge_model.html'},
}


def _list(request, kind, template):
    spec = CATALOGUES[kind]
    items = spec['model'].objects.all()
    if request.method == 'POST':
        selected = request.POST.getlist('selected')
        if 'delete' in request.POST:
            spec['model'].objects.filter(pk__in=selected).delete()
        elif 'duplicate' in request.POST and len(selected) == 1:
            original = get_object_or_404(spec['model'], pk=selected[0])
            original.pk = None
            original.model = f'{original.model} (copy)'
            original.save()
        return redirect(spec['list'])
    return render(request, template, {'items': items})


def _edit(request, kind, pk=None):
    spec = CATALOGUES[kind]
    item = get_object_or_404(spec['model'], pk=pk) if pk else None
    if request.method == 'POST' and 'delete' in request.POST:
        if item is not None:
            item.delete()
            messages.success(request, f'{spec["noun"].capitalize()} deleted.')
        return redirect(spec['list'])
    form = spec['form'](request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        item = form.save()
        messages.success(request, f'"{item.model}" saved.')
        return redirect(spec['edit'], pk=item.pk)
    return render(request, spec['template'], {'form': form, 'item': item, 'import_form': CatalogueImportForm()})


def probe_model_list(request):
    return _list(request, 'probe', 'equipment/probe_model_list.html')


def edit_probe_model(request, pk=None):
    return _edit(request, 'probe', pk)


def wedge_model_list(request):
    return _list(request, 'wedge', 'equipment/wedge_model_list.html')


def edit_wedge_model(request, pk=None):
    return _edit(request, 'wedge', pk)


def import_catalogue(request):
    """Adds or updates probe and wedge models from instrument / Beamtool files (several at once)."""
    back = request.POST.get('next')
    if back not in ('probe-model-list', 'wedge-model-list'):
        back = 'wedge-model-list'
    files = request.FILES.getlist('file') if request.method == 'POST' else []
    if not files:
        messages.error(request, 'Choose a file to import.')
        return redirect(back)
    probes, wedges = [], []
    for uploaded in files:
        try:
            found_probes, found_wedges = read_catalogue_file(uploaded)
        except CatalogueImportError as e:
            messages.error(request, str(e))
            return redirect(back)
        probes += found_probes
        wedges += found_wedges
    summary = apply_catalogue(probes, wedges)
    if summary:
        messages.success(request, f'Import: {summary}.')
    else:
        messages.warning(request, 'No probes or wedges were found in that file.')
    return redirect(back)


ADDABLE_FIELDS = {
    'probe': {'model', 'series', 'manufacturer', 'frequency', 'elements', 'pitch', 'elevation', 'length'},
    'wedge': {'model', 'probe_series', 'manufacturer', 'length', 'width', 'height', 'velocity', 'wedge_angle',
              'primary_offset', 'first_element_height'},
}


@require_POST
def add_from_file(request):
    """
    Adds a probe or wedge that an instrument file used to the catalogue (the NDE import's 'Add to
    catalogue'). JSON body: {"kind": "probe" | "wedge", "fields": {...}, "file": "scan.nde"}.
    Returns {"pk": ..., "name": ...}.
    """
    try:
        body = json.loads(request.body or b'{}')
        kind, fields = body['kind'], dict(body['fields'])
        allowed = ADDABLE_FIELDS[kind]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error': 'Send kind ("probe" or "wedge") and fields.'}, status=400)
    fields = {k: v for k, v in fields.items() if k in allowed and v not in (None, '')}
    if not fields.get('model'):
        return JsonResponse({'error': 'The file gives no model name.'}, status=400)
    filename = str(body.get('file') or 'an instrument file')[:200]
    fields['source'] = f'OmniScan file {filename}'
    probes, wedges = ([fields], []) if kind == 'probe' else ([], [fields])
    apply_catalogue(probes, wedges)
    model_class = ProbeModel if kind == 'probe' else WedgeModel
    item = model_class.objects.get(model=fields['model'])
    return JsonResponse({'pk': item.pk, 'name': str(item)})
