from django.shortcuts import render, redirect
from ..forms import SetupForm
import h5py
import io
import json


def nde_upload(request):
    """
    Upload and parse an .nde file, displaying the embedded JSON metadata.
    Also renders a Setup form that can be populated from the parsed JSON and saved.
    """
    context = {'form': SetupForm()}
    if request.method == 'POST':
        if 'nde_file' in request.FILES:
            uploaded = request.FILES['nde_file']
            if not uploaded.name.endswith('.nde'):
                context['error'] = 'Please upload a valid .nde file.'
            else:
                try:
                    file_bytes = io.BytesIO(uploaded.read())
                    with h5py.File(file_bytes, 'r') as f:
                        if 'Public/Setup' not in f:
                            context['error'] = 'No Setup metadata found in this .nde file.'
                        else:
                            raw = f['Public/Setup'][()]
                            setup_data = json.loads(raw.decode('utf-8'))
                            context['json_output'] = json.dumps(setup_data, indent=2)
                except Exception as e:
                    context['error'] = f'Failed to parse file: {e}'
        elif 'save_setup' in request.POST:
            form = SetupForm(request.POST)
            if form.is_valid():
                form.save()
                return redirect('setup-list')
            context['form'] = form
    return render(request, 'reports/nde_upload.html', context)
