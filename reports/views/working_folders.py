"""
Preferences › Working folders: the parent folders each report type's job folders are kept in, and
the Browse… button's folder dialog (shown on the computer running the app).
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..forms import WorkingFolderForm
from ..models import WorkingFolder
from ..services.job_folder import pick_folder

LOCAL_ADDRESSES = {'127.0.0.1', '::1', 'localhost'}


@require_POST
def browse_folder(request):
    """Browse…: opens the Windows folder dialog and returns {path} ('' when cancelled) or {error}."""
    if request.META.get('REMOTE_ADDR') not in LOCAL_ADDRESSES:
        # The dialog would open on the server's screen, not this person's
        return JsonResponse({'error': 'Browse only works on the computer running the app; type the path instead.'})
    try:
        path = pick_folder(request.POST.get('initial', ''), request.POST.get('title') or 'Select a folder')
    except Exception as e:   # no display, Tk missing, timed out…
        return JsonResponse({'error': f'The folder dialog couldn\'t open ({e}); type the path instead.'})
    return JsonResponse({'path': path})


def working_folder_list(request):
    folders = WorkingFolder.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            # Deleting only forgets the folder; nothing on disk is touched
            for folder in WorkingFolder.objects.filter(pk__in=selected_pks):
                folder.delete()
                successor = WorkingFolder.objects.filter(report_type=folder.report_type).first()
                if folder.is_default and successor is not None:
                    successor.is_default = True
                    successor.save()
            return redirect('working-folder-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-working-folder', pk=selected_pks[0])
    return render(request, 'reports/working_folder_list.html', {'items': folders})


def _edit(request, folder):
    if request.method == 'POST' and 'delete' in request.POST:
        if folder.pk:
            folder.delete()
            messages.success(request, 'Working folder removed (the folder itself is untouched).')
        return redirect('working-folder-list')
    form = WorkingFolderForm(request.POST or None, instance=folder,
                             initial={'report_type': request.GET.get('type', '')} if not folder.pk else None)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        messages.success(request, f'{saved.name} saved for {saved.report_type_label} reports.')
        # Back to the page that sent here (e.g. Guided Creation), but only to a page of this app
        target = request.POST.get('next')
        if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            return redirect(target)
        return redirect('working-folder-list')
    return render(request, 'reports/edit_working_folder.html', {'form': form, 'folder': folder if folder.pk else None})


def new_working_folder(request):
    return _edit(request, WorkingFolder())


def edit_working_folder(request, pk):
    return _edit(request, get_object_or_404(WorkingFolder, pk=pk))
