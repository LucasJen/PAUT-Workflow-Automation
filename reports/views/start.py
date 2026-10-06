"""
New weld report from files: pick the job folder (or make one, or just drop files), confirm the
welds its .nde files are of, and get the report built (reports/services/job_import.py), then
finish it in the guided editor. A job folder's name gives the report name, client and NPS
(reports/services/job_folder.py), and the downloads are saved into it.
"""
import os
import re

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render

from equipment.models import SensitivityBlock

from ..materials import _nps
from ..models import ClientCode, ReportDefaults
from ..services.job_folder import (
    folder_name, invalid_name, job_folders, jobs_root, nde_files, parse_folder_name, resolve_job_folder,
    save_uploads, set_jobs_root, split_welds,
)
from ..services.job_import import WELD_TYPE, build_report, job_block, read_job_file
from ..services.nde_parser import UNIT_SYSTEMS
from .reports import wizard_url

SESSION_KEY = 'job_import'
FOLDER_MODES = ('existing', 'new', 'none')


def _weld_defaults():
    return list(ReportDefaults.objects.filter(report_type=WELD_TYPE).order_by('-in_use', 'name'))


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


def _pipe_sizes():
    """The NPS the sensitivity block library has blocks for, smallest first: ['2', '3', '4', …]."""
    sizes = {_nps(b.pipe_size) for b in SensitivityBlock.objects.all()} - {''}
    return sorted(sizes, key=lambda s: float(s) if re.fullmatch(r'\d+(?:\.\d+)?', s) else 999)


def _new_folder_name(post):
    return folder_name(post.get('new_client', ''), post.get('new_unit', ''), post.get('new_line', ''),
                       split_welds(post.get('new_welds', '')), post.get('new_nps', ''))


def job_folder_name(request):
    """The New folder form's name preview: {name, error, exists}."""
    name = _new_folder_name(request.GET)
    error = '' if request.GET.get('new_line', '').strip() else 'Fill in at least the client and line.'
    error = error or invalid_name(name)
    root = jobs_root()
    return JsonResponse({'name': name, 'error': error, 'exists': bool(name) and (root / name).is_dir()})


def _job_folder(request, mode, uploads):
    """
    The job folder the start form picked or asked for (made when new), or None for no folder.
    Raises ValueError with what's wrong.
    """
    if mode == 'existing':
        folder = resolve_job_folder(request.POST.get('job_folder', ''))
        if folder is None:
            raise ValueError('Pick a job folder from the list (or choose New folder).')
        return folder
    if mode == 'new':
        if not request.POST.get('new_line', '').strip():
            raise ValueError('Fill in at least the client and line for the new folder.')
        name = _new_folder_name(request.POST)
        problem = invalid_name(name)
        if problem:
            raise ValueError(problem)
        root = jobs_root()
        if not root.is_dir():
            raise ValueError(f'The jobs folder {root} doesn\'t exist; change it at the top of the page.')
        if not uploads:
            raise ValueError('Choose the job\'s .nde files to copy into the new folder.')
        folder = root / name
        if folder.is_dir():
            messages.info(request, f'{name} already existed; the files went into it.')
        folder.mkdir(exist_ok=True)
        return folder
    return None


def start_from_files(request):
    """Step 1: the job folder (or files), the defaults set to start from, the NPS / Sch."""
    if request.method == 'POST' and 'set_root' in request.POST:
        problem = set_jobs_root(request.POST.get('jobs_root', ''))
        if problem:
            messages.error(request, problem)
        else:
            messages.success(request, f'Job folders are now listed from {jobs_root()}.')
        return redirect('start-from-files')

    # The page opens on Existing folder; a post without a mode is files only (as before job folders)
    mode = request.POST.get('folder_mode') if request.POST.get('folder_mode') in FOLDER_MODES else (
        'none' if request.method == 'POST' else 'existing')
    if request.method == 'POST':
        uploads = [f for f in request.FILES.getlist('nde_files') if f.name.lower().endswith('.nde')]
        try:
            folder = _job_folder(request, mode, uploads)
            if folder is not None:
                saved = save_uploads(folder, uploads)
                if saved:
                    messages.info(request, f'Copied {len(saved)} file{"s" if len(saved) != 1 else ""} into {folder.name}.')
                sources = nde_files(folder)
                if not sources:
                    raise ValueError(f'{folder.name} has no .nde files yet; add them with the file picker.')
            else:
                sources = uploads
                if not sources:
                    raise ValueError('Choose the job\'s .nde files.')
        except ValueError as e:
            messages.error(request, str(e))
        else:
            units = request.POST.get('units') if request.POST.get('units') in UNIT_SYSTEMS else 'imperial'
            files = [read_job_file(f, units) for f in sources]
            files.sort(key=lambda f: (f.get('weld') or '~', f['filename']))
            request.session[SESSION_KEY] = {
                'files': files,
                'defaults': request.POST.get('defaults') or '',
                'sensitivity_block': request.POST.get('sensitivity_block') or '',
                'folder': str(folder) if folder is not None else '',
            }
            return redirect('confirm-job')

    root = jobs_root()
    codes = {c.code: c for c in ClientCode.objects.all()}
    folders = job_folders(root)
    for item in folders:
        item['client'] = codes.get(item['info']['client_code'])
    return render(request, 'reports/start_from_files.html', {
        'defaults_sets': _weld_defaults(), 'blocks': SensitivityBlock.objects.all(),
        'root': root, 'root_exists': root.is_dir(), 'folders': folders, 'client_codes': codes.values(),
        'pipe_sizes': _pipe_sizes(), 'mode': mode, 'posted': request.POST,
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
    files = job['files']
    defaults = ReportDefaults.objects.filter(pk=job['defaults']).first() if str(job['defaults']).isdigit() else None
    readable = [f for f in files if not f.get('error')]
    folder, info, client = _folder_context(job, files)
    # The NPS: the folder name's, else the defaults' (Auto-detect then picks the schedule by the wall)
    folder_nps = f'{info["nps"]}in' if info and info['nps'] else ''
    pipe_size = folder_nps or ((defaults.report_values or {}).get('pipe_size', '') if defaults else '')

    if request.method == 'POST':
        kept = []
        for i, data in enumerate(files):
            if data.get('error') or not request.POST.get(f'include_{i}'):
                continue
            weld = request.POST.get(f'weld_{i}', '').strip().upper()
            kept.append({**data, 'weld': weld or data.get('weld') or 'W?'})
        if not kept:
            messages.error(request, 'Keep at least one file.')
        else:
            report, notes = build_report(kept, defaults, request.POST.get('document_filename', '').strip(),
                                         _picked_block(request.POST.get('sensitivity_block')),
                                         job_folder=folder or '', pipe_size=pipe_size, client=client)
            request.session.pop(SESSION_KEY, None)
            messages.success(request, f'Report made from {len(kept)} file{"s" if len(kept) != 1 else ""}. '
                                      'Go through the steps and fill in what\'s outlined; Next saves as you go.')
            for note in notes:
                messages.warning(request, note)
            return redirect(wizard_url(report))

    # The block picked on the first page, else the one the files' part (and folder NPS) point to
    picked = _picked_block(job.get('sensitivity_block'))
    detected, why = (None, '') if picked else job_block(readable, pipe_size)
    if detected is not None and not why and folder_nps:
        walls = sorted({f['thickness'] for f in readable if f.get('thickness') is not None})
        why = f'From the folder name ({folder_nps})' + (f' and the files\' {walls[0]:.3f}" wall.' if walls else '.')
    # Files whose weld the folder name doesn't list
    folder_welds = set(info['welds']) if info else set()
    for data in readable:
        data['not_in_folder'] = bool(folder_welds and data.get('weld') and data['weld'] not in folder_welds)
    scopes = sorted({item['scope'] for f in readable for item in f['items'] if item.get('scope')})
    return render(request, 'reports/confirm_job.html', {
        'files': files, 'defaults': defaults, 'scopes': scopes, 'blocks': SensitivityBlock.objects.all(),
        'job_block': picked or detected, 'block_picked': picked is not None, 'block_note': why,
        'document_filename': os.path.basename(folder) if folder else _suggested_name(readable),
        'folder': folder, 'folder_info': info, 'client': client,
    })
