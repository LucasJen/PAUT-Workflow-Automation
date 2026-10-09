"""
Guided Creation: pick the report type and the job folder (or make one, or just drop files), then
for a weld report confirm the welds its .nde files are of and pick the NPS / Sch
(reports/services/job_import.py), for a corrosion report say what the folder's pictures are
(start_corrosion.py); the report is built and finished in the guided editor. A job folder's name
gives the report name and client (reports/services/job_folder.py), and the downloads are saved
into it.
"""
import os
import re
from pathlib import Path

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode

from equipment.models import SensitivityBlock

from ..models import ClientCode, ReportDefaults
from ..report_types import REPORT_TYPES, guided_report_types
from ..services.job_folder import (
    invalid_name, job_folders, nde_files, parse_folder_name, resolve_job_folder, save_uploads, working_folder,
)
from ..services.corrosion_import import CORROSION_TYPE, PICTURE_TYPES, folder_pictures, read_corrosion_file
from ..services.job_import import WELD_TYPE, build_report, read_job_file
from ..services.nde_parser import UNIT_SYSTEMS
from .reports import wizard_url
from .start_corrosion import confirm_corrosion

SESSION_KEY = 'job_import'
FOLDER_MODES = ('existing', 'new', 'none')


def _type_defaults(report_type):
    return list(ReportDefaults.objects.filter(report_type=report_type).order_by('-in_use', 'name'))


def _picked_block(value):
    """The library sensitivity block a dropdown's value names (None for Auto-detect)."""
    return SensitivityBlock.objects.filter(pk=value).first() if str(value or '').isdigit() else None


def _suggested_name(files):
    """'PPI 31-37575 w5 n off1', 'PPI 31-37575 w6 s off1' -> 'PPI-31-37575-W5&W6'."""
    stems = [os.path.splitext(f['filename'])[0] for f in files]
    prefix = os.path.commonprefix(stems) if stems else ''
    prefix = re.sub(r'[\s_-]*(?:f?w\d*)?[\s_-]*$', '', prefix, flags=re.I).strip()
    welds = list(dict.fromkeys(f['weld'] for f in files if f.get('weld')))
    parts = [re.sub(r'\s+', '-', prefix)] if prefix else []
    if welds:
        parts.append('&'.join(welds))
    return '-'.join(parts)


def _job_folder(request, mode, uploads, root, needs_files=True):
    """
    The job folder the start form picked or asked for (made when new), or None for no folder.
    Raises ValueError with what's wrong.
    """
    if mode in ('existing', 'new') and root is None:
        raise ValueError('Set a working folder for these reports in Preferences › Working folders first, or choose Files only.')
    if mode == 'existing':
        folder = resolve_job_folder(request.POST.get('job_folder', ''), root.path)
        if folder is None:
            raise ValueError('Pick a job folder from the list (or choose New folder).')
        return folder
    if mode == 'new':
        name = request.POST.get('new_name', '').strip()
        problem = invalid_name(name)
        if problem:
            raise ValueError(problem)
        if not os.path.isdir(root.path):
            raise ValueError(f'The working folder {root.path} isn\'t there; change it in Preferences › Working folders.')
        if not uploads and needs_files:
            raise ValueError('Choose the job\'s .nde files to copy into the new folder.')
        folder = Path(root.path) / name
        if folder.is_dir():
            messages.info(request, f'{name} already existed; the files went into it.')
        folder.mkdir(exist_ok=True)
        return folder
    return None


def _start_url(rtype):
    return f"{reverse('start-from-files')}?{urlencode({'type': rtype.key})}"


def start_from_files(request):
    """
    Step 1: the report type (?type=, weld by default; only types with a guided workflow go on),
    the job folder in its default working folder (set in Preferences) or files only, the defaults
    set to start from, optionally the NPS / Sch.
    """
    key = request.POST.get('type') or request.GET.get('type')
    rtype = REPORT_TYPES.get(key) or REPORT_TYPES[WELD_TYPE]
    root = working_folder(rtype.key)

    # The page opens on Existing folder; a post without a mode is files only (as before job folders)
    mode = request.POST.get('folder_mode') if request.POST.get('folder_mode') in FOLDER_MODES else (
        'none' if request.method == 'POST' else 'existing')
    if request.method == 'POST' and not rtype.guided:
        messages.error(request, f'Guided Creation can\'t build {rtype.label} reports yet; use New report.')
        return redirect(_start_url(rtype))
    # A corrosion or Long Form job may have no .nde files at all (manual UT): its pictures matter more
    picture_flow = rtype.key in PICTURE_TYPES
    if request.method == 'POST':
        uploads = [f for f in request.FILES.getlist('nde_files') if f.name.lower().endswith('.nde')]
        try:
            folder = _job_folder(request, mode, uploads, root, needs_files=not picture_flow)
            if folder is not None:
                saved = save_uploads(folder, uploads)
                if saved:
                    messages.info(request, f'Copied {len(saved)} file{"s" if len(saved) != 1 else ""} into {folder.name}.')
                sources = nde_files(folder)
                if not sources and not picture_flow:
                    raise ValueError(f'{folder.name} has no .nde files yet; add them with the file picker.')
            else:
                sources = uploads
                if not sources:
                    raise ValueError('Choose the job\'s .nde files.')
        except ValueError as e:
            messages.error(request, str(e))
        else:
            units = request.POST.get('units') if request.POST.get('units') in UNIT_SYSTEMS else 'imperial'
            job = {'type': rtype.key, 'defaults': request.POST.get('defaults') or '',
                   'folder': str(folder) if folder is not None else ''}
            if picture_flow:
                files = sorted((read_corrosion_file(f, units) for f in sources), key=lambda f: f['filename'].lower())
                job.update(files=files, pictures=folder_pictures(folder) if folder is not None else [])
            else:
                files = [read_job_file(f, units) for f in sources]
                files.sort(key=lambda f: (f.get('weld') or '~', f['filename']))
                job.update(files=files, sensitivity_block=request.POST.get('sensitivity_block') or '')
            request.session[SESSION_KEY] = job
            return redirect('confirm-job')

    codes = {c.code: c for c in ClientCode.objects.all()}
    folders = job_folders(root.path) if root is not None and rtype.guided else []
    for item in folders:
        item['client'] = codes.get(item['info']['client_code'])
        if picture_flow:   # these folders aren't named like weld jobs: any with files or pictures is one
            item['job'] = bool(item['nde'] or item['pictures'])
    if picture_flow:
        folders.sort(key=lambda f: (not f['job'], -f['modified'].timestamp()))
    return render(request, 'reports/start_from_files.html', {
        'defaults_sets': _type_defaults(rtype.key), 'blocks': SensitivityBlock.objects.all(),
        'picture_flow': picture_flow,
        'rtype': rtype, 'report_types': guided_report_types(),
        'root': root, 'root_exists': root is not None and os.path.isdir(root.path),
        'folders': folders, 'mode': mode, 'posted': request.POST,
    })


def _folder_context(job, files):
    """What the job folder's name says, for the confirm page: (folder Path or None, info, client)."""
    folder = job.get('folder') or ''
    if not folder:
        return None, None, None
    info = parse_folder_name(os.path.basename(folder))
    client = ClientCode.objects.filter(code=info['client_code']).first() if info['client_code'] else None
    # A file the name gave no weld gets the folder's, when the folder is of one weld
    if len(info['welds']) == 1:
        for data in files:
            if not data.get('error') and not data.get('weld'):
                data['weld'] = info['welds'][0]
    return folder, info, client


def confirm_job(request):
    """Step 2: which weld each file is of, the report's name; then build it and open the editor."""
    job = request.session.get(SESSION_KEY)
    if not job:
        return redirect('start-from-files')
    if job.get('type') in PICTURE_TYPES:
        return confirm_corrosion(request, job)
    files = job['files']
    defaults = ReportDefaults.objects.filter(pk=job['defaults']).first() if str(job['defaults']).isdigit() else None
    readable = [f for f in files if not f.get('error')]
    folder, info, client = _folder_context(job, files)

    if request.method == 'POST':
        kept = []
        for i, data in enumerate(files):
            if data.get('error') or not request.POST.get(f'include_{i}'):
                continue
            weld = request.POST.get(f'weld_{i}', '').strip().upper()
            kept.append({**data, 'weld': weld or data.get('weld') or 'W?'})
        block = _picked_block(request.POST.get('sensitivity_block'))
        if not kept:
            messages.error(request, 'Keep at least one file.')
        elif block is None:
            messages.error(request, 'Pick the NPS / Sch.')
        else:
            report, notes = build_report(kept, defaults, request.POST.get('document_filename', '').strip(), block,
                                         job_folder=folder or '', client=client)
            request.session.pop(SESSION_KEY, None)
            messages.success(request, f'Report made from {len(kept)} file{"s" if len(kept) != 1 else ""}. '
                                      'Go through the steps and fill in what\'s outlined; Next saves as you go.')
            for note in notes:
                messages.warning(request, note)
            return redirect(wizard_url(report))

    # The NPS / Sch is picked by hand (on the first page or here); the wall the files recorded helps
    picked = _picked_block(request.POST.get('sensitivity_block') or job.get('sensitivity_block'))
    walls = sorted({round(f['thickness'], 3) for f in readable if f.get('thickness') is not None})
    # Files whose weld the folder name doesn't list
    folder_welds = set(info['welds']) if info else set()
    for data in readable:
        data['not_in_folder'] = bool(folder_welds and data.get('weld') and data['weld'] not in folder_welds)
    scopes = sorted({item['scope'] for f in readable for item in f['items'] if item.get('scope')})
    return render(request, 'reports/confirm_job.html', {
        'files': files, 'defaults': defaults, 'scopes': scopes, 'blocks': SensitivityBlock.objects.all(),
        'job_block': picked, 'walls': walls,
        'document_filename': os.path.basename(folder) if folder else _suggested_name(readable),
        'folder': folder, 'folder_info': info, 'client': client,
    })
