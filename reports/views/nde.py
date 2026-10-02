from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from equipment.importers import probe_from_nde, wedge_from_nde
from equipment.matching import match_probe, match_wedge
from ..forms import SetupForm
from ..services.nde_parser import UNIT_SYSTEMS, NdeError, extract_groups, read_nde
from ..weld_columns import columns_from_setup
import json


def _catalogue_match(hardware):
    """
    The catalogue probe and wedge for a group's hardware: ({setup field: value} to fill in, and a
    summary for the page with what matched, how, geometry differences, and the file's own values
    for 'Add to catalogue' when nothing matched).
    """
    file_probe = probe_from_nde(hardware['probe']) if hardware.get('probe') else {}
    file_wedge = wedge_from_nde(hardware['wedge'], hardware.get('mounting_id')) if hardware.get('wedge') else {}
    probe = match_probe(file_probe) if file_probe else None
    wedge = match_wedge(file_wedge, probe.item if probe else None) if file_wedge else None

    def summary(match, file_fields):
        if not file_fields:
            return None
        if match is None or match.item is None:
            return {'file_name': file_fields.get('model', ''), 'file_fields': file_fields}
        info = {'file_name': file_fields.get('model', ''), 'pk': match.item.pk, 'name': str(match.item),
                'how': match.how, 'differences': match.differences}
        suggestion = getattr(match, 'suggestion', None)
        if suggestion is not None:
            info['suggestion'] = {'pk': suggestion.pk, 'name': str(suggestion)}
        return info

    fill = {
        'catalogue_probe': probe.item.pk if probe and probe.item else '',
        'catalogue_wedge': wedge.item.pk if wedge and wedge.item else '',
        'first_element': hardware.get('first_element') or '',
        'aperture_elements': hardware.get('aperture') or '',
    }
    return fill, {'probe': summary(probe, file_probe), 'wedge': summary(wedge, file_wedge)}


def nde_upload(request):
    """
    Upload an .nde file and fill a Setup form from its metadata (one candidate setup per
    inspection group, in imperial and metric), with the probe and wedge matched to the catalogue.
    The setup is saved from the same page.
    """
    context = {'form': SetupForm()}
    if request.method == 'POST':
        if 'nde_file' in request.FILES:
            uploaded = request.FILES['nde_file']
            if not uploaded.name.lower().endswith('.nde'):
                context['error'] = 'Please upload a valid .nde file.'
            else:
                try:
                    setup, properties = read_nde(uploaded)
                    groups = extract_groups(setup, properties, uploaded.name)
                    if not groups:
                        context['error'] = 'This .nde file has no inspection groups to import.'
                    else:
                        for group in groups:
                            fill, group['catalogue'] = _catalogue_match(group.pop('hardware', {}))
                            for values in group['values'].values():
                                values.update(fill)
                        context['nde_groups'] = groups
                        context['nde_filename'] = uploaded.name
                        context['json_output'] = json.dumps(setup, indent=2)
                except NdeError as e:
                    context['error'] = str(e)
        elif 'save_setup' in request.POST:
            form = SetupForm(request.POST)
            if form.is_valid():
                setup = form.save()
                messages.success(request, f'Setup #{setup.pk} saved.')
                return redirect('setup-list')
            context['form'] = form
    return render(request, 'reports/nde_upload.html', context)


@require_POST
def nde_columns(request):
    """
    The weld form grid's "Import .nde": {'columns': [{instrument, probe, group, probe_key, label}]},
    one per inspection group in the file, in the chosen units, with the probe and wedge matched
    to the catalogue; or {'error': ...}.
    """
    uploaded = request.FILES.get('nde_file')
    system = request.POST.get('units')
    if system not in UNIT_SYSTEMS:
        system = 'imperial'
    if uploaded is None or not uploaded.name.lower().endswith('.nde'):
        return JsonResponse({'error': 'Please choose an .nde file.'}, status=400)
    try:
        setup, properties = read_nde(uploaded)
    except NdeError as e:
        return JsonResponse({'error': str(e)}, status=400)
    columns = []
    for group in extract_groups(setup, properties, uploaded.name):
        fill, _ = _catalogue_match(group.get('hardware', {}))
        values = {**group['values'][system], **fill}
        # The group's name for the column label ('GR-1 · Sectorial · 40°–70°' -> 'GR-1')
        columns.append({**columns_from_setup(values), 'label': group['label'].split(' · ')[0], 'title': group['label']})
    if not columns:
        return JsonResponse({'error': 'This .nde file has no inspection groups to import.'}, status=400)
    return JsonResponse({'columns': columns, 'filename': uploaded.name})
