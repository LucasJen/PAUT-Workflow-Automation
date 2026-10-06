"""The report's job folder bar (editor and preview): open the folder, change it or clear it."""
import os

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import Report
from ..services.job_folder import resolve_job_folder, working_folders


def _back(request, report):
    target = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect('edit-report', pk=report.pk)


def report_job_folder(request, pk):
    """POST open / set (a folder in the jobs root, or any folder's full path) / clear."""
    report = get_object_or_404(Report, pk=pk)
    if request.method != 'POST':
        return _back(request, report)
    action = request.POST.get('action')
    if action == 'open':
        if report.job_folder and os.path.isdir(report.job_folder) and hasattr(os, 'startfile'):
            os.startfile(report.job_folder)   # File Explorer, on the PC running the app
        else:
            messages.error(request, f'The job folder {report.job_folder} isn\'t there.')
    elif action == 'set':
        value = request.POST.get('job_folder', '').strip().strip('"')
        in_roots = (resolve_job_folder(value, root.path) for root in working_folders(report.report_type))
        folder = next((f for f in in_roots if f is not None), None) or (
            value if os.path.isabs(value) and os.path.isdir(value) else None)
        if folder is None:
            messages.error(request, f'No folder “{value}” (a folder in a working folder, or a full path).')
        elif str(folder) != report.job_folder:
            # A new folder: none of its files are the app's yet
            Report.objects.filter(pk=pk).update(job_folder=str(folder), job_folder_files=[])
            messages.success(request, f'Downloads now also save into {folder}.')
    elif action == 'clear':
        Report.objects.filter(pk=pk).update(job_folder='', job_folder_files=[])
        messages.success(request, 'The report is no longer tied to a job folder.')
    return _back(request, report)
