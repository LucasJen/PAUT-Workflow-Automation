from django.contrib import messages
from django.shortcuts import render, redirect
from equipment.importers import probe_from_nde, wedge_from_nde
from equipment.matching import match_probe, match_wedge
from ..forms import SetupForm
from ..services.nde_parser import NdeError, extract_groups, read_nde
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
        return {'file_name': file_fields.get('model', ''), 'pk': match.item.pk, 'name': str(match.item),
                'how': match.how, 'differences': match.differences}

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
