import json
import os

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import importer, runner
from .checks import LAYERS
from .kit import ROLES, Kit, KitError
from .models import ValidationRun, ValidationSettings


def _run_json(run):
    return {'id': run.pk, 'status': run.status, 'created': run.created_at.isoformat(),
            'finished': run.finished_at.isoformat() if run.finished_at else None, 'version': run.version,
            'computer': run.computer, 'kit_path': run.kit_path, 'manifest_sha': run.manifest_sha,
            'options': run.options, 'passed': run.passed, 'failed': run.failed, 'results': run.results}


def validation(request):
    """The Validation page: the kit, starting a run, and the runs so far (one shown in full)."""
    settings = ValidationSettings.get()
    if request.method == 'POST':
        if 'kit_path' in request.POST:
            settings.kit_path = request.POST['kit_path'].strip()
            settings.save()
            messages.success(request, 'Kit folder saved.')
        elif 'add_file' in request.POST:
            roles = request.POST.getlist('roles')
            try:
                entry = Kit(settings.kit).add(request.POST.get('file', '').strip().strip('"'), roles,
                                                   request.POST.get('source', '').strip(), request.POST.get('notes', '').strip())
                messages.success(request, f"Added {entry['path']} to the kit.")
            except (KitError, OSError) as e:
                messages.error(request, str(e))
        elif 'import_export' in request.POST:
            try:
                kit = Kit(settings.kit)
                nde = next((e for e in kit.nde_files() if e['path'] == request.POST.get('nde')), None)
                if nde is None:
                    raise KitError('Pick the .nde file the export was made from (add it to the kit first).')
                entries = importer.import_export(kit, request.POST.get('export', '').strip().strip('"'), nde,
                                                 request.POST.get('source', '').strip())
                messages.success(request, f"Imported: {', '.join(e['notes'] for e in entries)} from the export.")
            except (KitError, importer.ImportError_, OSError, ValueError) as e:
                messages.error(request, str(e))
        return redirect('validation')

    runner.mark_abandoned()
    kit, kit_error = None, ''
    try:
        kit = Kit(settings.kit)
    except KitError as e:
        kit_error = str(e)
    runs = list(ValidationRun.objects.all()[:25])
    shown = None
    if request.GET.get('run'):
        shown = get_object_or_404(ValidationRun, pk=request.GET['run'])
    elif runs:
        shown = runs[0]
    files = []
    if kit:
        for e in kit.files:
            files.append({**e, 'present': os.path.isfile(kit.full_path(e)),
                          'role_names': [ROLES.get(r, r) for r in e.get('roles') or []]})
    return render(request, 'validation/validation.html', {
        'settings': settings, 'kit': kit, 'kit_error': kit_error, 'kit_files': files,
        'kit_size': sum(e.get('size') or 0 for e in files), 'kit_nde': kit.nde_files() if kit else [], 'roles': ROLES.items(), 'layers': LAYERS,
        'runs': runs, 'shown': _run_json(shown) if shown else None, 'sweep_default': runner.default_sweep(),
    })


@require_POST
def run_start(request):
    body = json.loads(request.body or '{}')
    options = {}
    if body.get('sweep'):
        options['sweep'] = os.path.abspath(os.path.expanduser(body['sweep']))
        if not os.path.isdir(options['sweep']):
            return JsonResponse({'error': f"No folder {options['sweep']}"}, status=400)
    if body.get('approve'):   # lock the current results as the approved baseline (L6 only)
        options['approve'] = str(body['approve']).strip()[:300]
        body['layers'] = ['L6']
    run = runner.create(body.get('layers') or [], ValidationSettings.get().kit, options)
    runner.start(run)
    return JsonResponse({'id': run.pk})


def run_status(request, pk):
    return JsonResponse(_run_json(get_object_or_404(ValidationRun, pk=pk)))


@require_POST
def run_cancel(request, pk):
    runner.cancel(pk)
    return JsonResponse({'ok': True})
