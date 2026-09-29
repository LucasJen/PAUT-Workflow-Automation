from django.contrib import messages
from django.shortcuts import render, redirect
from ..forms import SetupForm
from ..services.nde_parser import NdeError, extract_groups, read_nde
import json


def nde_upload(request):
    """
    Upload an .nde file and fill a Setup form from its metadata (one candidate setup per
    inspection group, in imperial and metric). The setup is saved from the same page.
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
