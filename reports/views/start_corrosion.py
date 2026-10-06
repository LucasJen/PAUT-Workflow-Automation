"""
Guided Creation, corrosion form (598-PAUTFORM-009), step 2: the report's name and unit / equipment,
which .nde files to use (each distinct setup gets a Setup Information page) and what each of the
job folder's pictures is (a drawing, a setup image, an image for the Images pages, or left out).
"""
import mimetypes
import os

from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render

from ..models import ReportDefaults
from ..services.corrosion_import import (
    ROLE_CHOICES, SKIP, build_corrosion_report, caption_for, distinct_setups, equipment_from_folder, guess_role,
)

SESSION_KEY = 'job_import'


def _picture_path(job, index):
    pictures = job.get('pictures') or []
    folder = job.get('folder') or ''
    if not folder or not 0 <= index < len(pictures):
        return None
    path = os.path.join(folder, pictures[index])
    return path if os.path.isfile(path) else None


def job_picture(request, index):
    """A picture of the job folder in the session, for the step's thumbnails."""
    path = _picture_path(request.session.get(SESSION_KEY) or {}, index)
    if path is None:
        raise Http404
    return FileResponse(open(path, 'rb'), content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream')


def confirm_corrosion(request, job):
    files = job['files']
    pictures = job.get('pictures') or []
    folder = job.get('folder') or ''
    folder_name = os.path.basename(folder) if folder else ''
    defaults = ReportDefaults.objects.filter(pk=job['defaults']).first() if str(job['defaults']).isdigit() else None
    readable = [f for f in files if not f.get('error')]
    roles = {key for key, _ in ROLE_CHOICES}

    if request.method == 'POST':
        kept = [data for i, data in enumerate(files) if not data.get('error') and request.POST.get(f'include_{i}')]
        chosen = []
        for i, name in enumerate(pictures):
            role = request.POST.get(f'role_{i}')
            role = role if role in roles else guess_role(name)
            if role != SKIP and (path := _picture_path(job, i)):
                chosen.append((path, role, request.POST.get(f'caption_{i}', '').strip()))
        report, notes = build_corrosion_report(
            kept, chosen, defaults, request.POST.get('document_filename', '').strip(),
            request.POST.get('equipment_id', '').strip(), job_folder=folder)
        request.session.pop(SESSION_KEY, None)
        made = [f'{len(kept)} file{"s" if len(kept) != 1 else ""}'] if kept else []
        if chosen:
            made.append(f'{len(chosen)} picture{"s" if len(chosen) != 1 else ""}')
        messages.success(request, f'Report made{" from " + " and ".join(made) if made else ""}. '
                                  'Go through the steps and fill in what\'s outlined; Next saves as you go.')
        for note in notes:
            messages.warning(request, note)
        from .reports import wizard_url
        return redirect(wizard_url(report))

    picture_rows = [{'index': i, 'name': name, 'role': guess_role(name), 'caption': caption_for(name)}
                    for i, name in enumerate(pictures)]
    setups = distinct_setups(readable)
    return render(request, 'reports/confirm_corrosion.html', {
        'files': files, 'defaults': defaults, 'folder': folder, 'pictures': picture_rows, 'role_choices': ROLE_CHOICES,
        'setups': setups, 'document_filename': folder_name, 'equipment_id': equipment_from_folder(folder_name),
    })
