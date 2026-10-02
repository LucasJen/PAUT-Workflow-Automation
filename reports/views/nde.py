from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from equipment.inventory import with_library_scope
from ..forms import SetupForm
from ..services.job_import import catalogue_match as _catalogue_match, file_items, scope_label as _scope_label
from ..services.nde_parser import UNIT_SYSTEMS, NdeError, extract_groups, read_nde
import json


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
                            for system, values in group['values'].items():
                                values.update(fill)
                                # The instrument's cal due, module... from the scope library (by S/N)
                                group['values'][system], scope = with_library_scope(values)
                            group['scope'] = _scope_label(scope)
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
def nde_setup_values(request):
    """
    The long form's "Import .nde" on a setup block: {'groups': [{label, values}], 'scope': ...}, one
    per inspection group, in the block's units, matched to the catalogue and completed from the
    scope library; or {'error': ...}.
    """
    uploaded = request.FILES.get('nde_file')
    system = request.POST.get('units') if request.POST.get('units') in UNIT_SYSTEMS else 'imperial'
    if uploaded is None or not uploaded.name.lower().endswith('.nde'):
        return JsonResponse({'error': 'Please choose an .nde file.'}, status=400)
    try:
        setup, properties = read_nde(uploaded)
    except NdeError as e:
        return JsonResponse({'error': str(e)}, status=400)
    groups, scope = [], None
    for group in extract_groups(setup, properties, uploaded.name):
        fill, _ = _catalogue_match(group.get('hardware', {}))
        values, scope = with_library_scope({**group['values'][system], **fill})
        groups.append({'label': group['label'], 'values': values})
    if not groups:
        return JsonResponse({'error': 'This .nde file has no inspection groups to import.'}, status=400)
    return JsonResponse({'groups': groups, 'scope': _scope_label(scope), 'filename': uploaded.name})


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
    columns = file_items(setup, properties, uploaded.name, system)
    if not columns:
        return JsonResponse({'error': 'This .nde file has no inspection groups to import.'}, status=400)
    return JsonResponse({'columns': columns, 'filename': uploaded.name})
