from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from ..forms import SetupForm
from ..models import Setup


def setup_list(request):
    """
    The saved setups: those not part of a report (a report's setups are edited, deleted and
    duplicated in its own editor), as the dashboard counts them
    """
    setups = Setup.objects.filter(report__isnull=True)
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            setups.filter(pk__in=selected_pks).delete()
            return redirect('setup-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-setup', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(setups, pk=selected_pks[0])
            images = list(original.images.all())
            original.pk = None  # clears the pk, forcing a new row on save
            original.save()
            for image in images:   # calibration screenshots too (the files are shared)
                image.pk, image.setup = None, original
                image.save()
            return redirect('setup-list')
    return render(request, 'reports/setup_list.html', {'items': setups})


def new_setup(request):
    """
    The edit page for a setup not saved yet: saving creates it (just opening the page doesn't)
    """
    return edit_setup(request)


def edit_setup(request, pk=None):
    """
    Edit a single setup from the setup list
    """
    setup = get_object_or_404(Setup, pk=pk) if pk is not None else Setup()
    if request.method == 'POST':
        if 'delete' in request.POST:
            if setup.pk is None:
                return redirect('setup-list')
            setup.delete()
            messages.success(request, 'Setup deleted.')
            return redirect('setup-list')
        form = SetupForm(request.POST, instance=setup)
        if form.is_valid():
            form.save()
            messages.success(request, 'Setup saved.')
            return redirect('setup-list')
    else:
        form = SetupForm(instance=setup)
    return render(request, 'reports/edit_setup.html', {'form': form, 'setup': setup})
