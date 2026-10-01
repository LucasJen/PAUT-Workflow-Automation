"""Probe and wedge catalogues: list, edit, and import from instrument files."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CatalogueImportForm, ProbeModelForm, WedgeModelForm
from .importers import CatalogueImportError, read_catalogue_file
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


def _apply(model_class, rows):
    """Creates or updates catalogue entries; returns ['Added X', 'Updated Y: a, b'] lines."""
    lines = []
    for row in rows:
        row = dict(row)
        name = row.pop('model')
        item, created = model_class.objects.get_or_create(model=name, defaults=row)
        if created:
            lines.append(f'added {name}')
            continue
        changed = [field for field, value in row.items() if getattr(item, field) != value]
        for field in changed:
            setattr(item, field, row[field])
        if changed:
            item.save()
            labels = ', '.join(str(model_class._meta.get_field(f).verbose_name) for f in changed)
            lines.append(f'updated {name} ({labels})')
        else:
            lines.append(f'{name} already up to date')
    return lines


def import_catalogue(request):
    """Adds or updates probe and wedge models from an instrument file (e.g. an OmniScan .nde)."""
    back = request.POST.get('next')
    if back not in ('probe-model-list', 'wedge-model-list'):
        back = 'wedge-model-list'
    form = CatalogueImportForm(request.POST or None, request.FILES or None)
    if request.method != 'POST' or not form.is_valid():
        messages.error(request, 'Choose a file to import.')
        return redirect(back)
    try:
        probes, wedges = read_catalogue_file(form.cleaned_data['file'])
    except CatalogueImportError as e:
        messages.error(request, str(e))
        return redirect(back)
    lines = _apply(ProbeModel, probes) + _apply(WedgeModel, wedges)
    if lines:
        messages.success(request, 'Import: ' + '; '.join(lines) + '.')
    else:
        messages.warning(request, 'No probes or wedges were found in that file.')
    return redirect(back)
