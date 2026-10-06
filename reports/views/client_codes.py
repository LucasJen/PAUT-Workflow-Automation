from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import ClientCodeForm
from ..models import ClientCode


def client_code_list(request):
    """Library › Client codes: the abbreviations job folders start with, and the client each means."""
    codes = ClientCode.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            ClientCode.objects.filter(pk__in=selected_pks).delete()
            return redirect('client-code-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-client-code', pk=selected_pks[0])
    return render(request, 'reports/client_code_list.html', {'items': codes})


def new_client_code(request):
    if request.method == 'POST' and 'delete' in request.POST:  # 'Delete' on an unsaved code = discard
        return redirect('client-code-list')
    form = ClientCodeForm(request.POST or None, initial={'code': request.GET.get('code', '')})
    if request.method == 'POST' and form.is_valid():
        code = form.save()
        messages.success(request, f'{code.code} added.')
        return redirect(request.POST.get('next') or 'client-code-list')
    return render(request, 'reports/edit_client_code.html', {'form': form, 'code': None})


def edit_client_code(request, pk):
    code = get_object_or_404(ClientCode, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            code.delete()
            messages.success(request, 'Client code deleted.')
            return redirect('client-code-list')
        form = ClientCodeForm(request.POST, instance=code)
        if form.is_valid():
            form.save()
            messages.success(request, f'{code.code} saved.')
            return redirect('client-code-list')
    else:
        form = ClientCodeForm(instance=code)
    return render(request, 'reports/edit_client_code.html', {'form': form, 'code': code})
