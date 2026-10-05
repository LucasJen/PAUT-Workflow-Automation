"""
New weld report from files: drop a job's .nde files, confirm the welds they're of, and get the
report built (reports/services/job_import.py), then finish it in the editor.
"""
import os
import re

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from equipment.models import SensitivityBlock

from ..models import ReportDefaults
from ..services.job_import import WELD_TYPE, build_report, job_block, read_job_file
from ..services.nde_parser import UNIT_SYSTEMS

SESSION_KEY = 'job_import'


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


def start_from_files(request):
    """Step 1: the defaults set to start from and the job's .nde files."""
    defaults = _weld_defaults()
    if request.method == 'POST':
        uploads = [f for f in request.FILES.getlist('nde_files') if f.name.lower().endswith('.nde')]
        if not uploads:
            messages.error(request, 'Choose the job\'s .nde files.')
        else:
            units = request.POST.get('units') if request.POST.get('units') in UNIT_SYSTEMS else 'imperial'
            files = [read_job_file(f, units) for f in uploads]
            files.sort(key=lambda f: (f.get('weld') or '~', f['filename']))
            request.session[SESSION_KEY] = {
                'files': files,
                'defaults': request.POST.get('defaults') or '',
                'sensitivity_block': request.POST.get('sensitivity_block') or '',
            }
            return redirect('confirm-job')
    return render(request, 'reports/start_from_files.html',
                  {'defaults_sets': defaults, 'blocks': SensitivityBlock.objects.all()})


def confirm_job(request):
    """Step 2: which weld each file is of, the report's name; then build it and open the editor."""
    job = request.session.get(SESSION_KEY)
    if not job:
        return redirect('start-from-files')
    files = job['files']
    defaults = ReportDefaults.objects.filter(pk=job['defaults']).first() if str(job['defaults']).isdigit() else None
    readable = [f for f in files if not f.get('error')]

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
                                         _picked_block(request.POST.get('sensitivity_block')))
            request.session.pop(SESSION_KEY, None)
            messages.success(request, f'Report made from {len(kept)} file{"s" if len(kept) != 1 else ""}. '
                                      'Fill in what\'s outlined, add the indications, then save and download.')
            for note in notes:
                messages.warning(request, note)
            return redirect(f"{reverse('create-report')}?loaded={report.pk}")

    # The block picked on the first page, else the one the files' part points to
    picked = _picked_block(job.get('sensitivity_block'))
    detected, why = (None, '') if picked else job_block(readable, (defaults.report_values or {}).get('pipe_size', '') if defaults else '')
    scopes = sorted({item['scope'] for f in readable for item in f['items'] if item.get('scope')})
    return render(request, 'reports/confirm_job.html', {
        'files': files, 'defaults': defaults, 'scopes': scopes, 'blocks': SensitivityBlock.objects.all(),
        'job_block': picked or detected, 'block_picked': picked is not None, 'block_note': why,
        'document_filename': _suggested_name(readable),
    })
