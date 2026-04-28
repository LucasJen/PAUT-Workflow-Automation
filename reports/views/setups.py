from django.shortcuts import render, redirect, get_object_or_404
from ..forms import SetupForm
from ..models import Setup


def setup_list(request):
    """
    View all setups that are currently in the database, references Setup model
    """
    setups = Setup.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected_setups')
        if 'delete' in request.POST:
            Setup.objects.filter(pk__in=selected_pks).delete()
            return redirect('setup-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-setup', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(Setup, pk=selected_pks[0])
            original.pk = None  # clears the pk, forcing a new row on save
            original.save()
            return redirect('setup-list')
    return render(request, 'reports/setup_list.html', {'setups': setups})


def new_setup(request):
    """
    Creates a blank setup and redirects to the edit view
    """
    setup = Setup.objects.create()
    return redirect('edit-setup', pk=setup.pk)


def edit_setup(request, pk):
    """
    Edit a single setup from the setup list
    """
    setup = get_object_or_404(Setup, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            setup.delete()
            return redirect('setup-list')
        form = SetupForm(request.POST, instance=setup)
        if form.is_valid():
            form.save()
            return redirect('setup-list')
    else:
        form = SetupForm(instance=setup)
    return render(request, 'reports/edit_setup.html', {'form': form, 'setup': setup})
