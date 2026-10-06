"""
New weld report from files: pick the job folder (or make one, or just drop files), confirm the
welds its .nde files are of and pick the NPS / Sch, and get the report built
(reports/services/job_import.py), then finish it in the guided editor. A job folder's name gives
the report name and client (reports/services/job_folder.py), and the downloads are saved into it.
"""
import os
import re
from pathlib import Path

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from equipment.models import SensitivityBlock

from ..models import ClientCode, ReportDefaults
from ..services.job_folder import (
    add_working_folder, invalid_name, job_folders, nde_files, parse_folder_name, resolve_job_folder, save_uploads,
    working_folder, working_folders,
)
from ..services.job_import import WELD_TYPE, build_report, read_job_file
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


def _job_folder(request, mode, uploads, root):
    """
    The job folder the start form picked or asked for (made when new), or None for no folder.
    Raises ValueError with what's wrong.
    """
    if mode in ('existing', 'new') and root is None:
        raise ValueError('Add a working folder for weld reports first (at the top of the page), or choose Files only.')
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
            raise ValueError(f'The working folder {root.path} isn\'t there; pick or add another at the top of the page.')
        if not uploads:
            raise ValueError('Choose the job\'s .nde files to copy into the new folder.')
        folder = Path(root.path) / name
        if folder.is_dir():
            messages.info(request, f'{name} already existed; the files went into it.')
        folder.mkdir(exist_ok=True)
        return folder
    return None


def start_from_files(request):
    """
    Step 1: the working folder (weld reports' parent folders; ?root=<pk>, else the default) and
    the job folder in it (or files only), the defaults set to start from, optionally the NPS / Sch.
    """
    if request.method == 'POST' and 'add_root' in request.POST:
        added, problem = add_working_folder(request.POST.get('root_path', ''), WELD_TYPE,
                                            is_default=bool(request.POST.get('root_default')))
        if problem:
            messages.error(request, problem)
            return redirect('start-from-files')
        messages.success(request, f'{added.name} added as a working folder for weld reports.')
        return redirect(f"{reverse('start-from-files')}?root={added.pk}")

    root = working_folder(WELD_TYPE, request.POST.get('root') or request.GET.get('root'))

    # The page opens on Existing folder; a post without a mode is files only (as before job folders)
    mode = request.POST.get('folder_mode') if request.POST.get('folder_mode') in FOLDER_MODES else (
        'none' if request.method == 'POST' else 'existing')
    if request.method == 'POST':
        uploads = [f for f in request.FILES.getlist('nde_files') if f.name.lower().endswith('.nde')]
        try:
            folder = _job_folder(request, mode, uploads, root)
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

    codes = {c.code: c for c in ClientCode.objects.all()}
    folders = job_folders(root.path) if root is not None else []
    for item in folders:
        item['client'] = codes.get(item['info']['client_code'])
    return render(request, 'reports/start_from_files.html', {
        'defaults_sets': _weld_defaults(), 'blocks': SensitivityBlock.objects.all(),
        'root': root, 'roots': working_folders(WELD_TYPE), 'root_exists': root is not None and os.path.isdir(root.path),
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
