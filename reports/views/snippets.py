from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import TextSnippetForm
from ..models import TextSnippet


def snippet_list(request):
    """
    Text library: technique descriptions and the standard Discussion used in reports
    """
    snippets = TextSnippet.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            TextSnippet.objects.filter(pk__in=selected_pks).delete()
            return redirect('snippet-list')
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(TextSnippet, pk=selected_pks[0])
            original.pk = None
            original.name = f'{original.name} (copy)'
            original.save()
            return redirect('snippet-list')
    return render(request, 'reports/snippet_list.html', {'items': snippets})


def new_snippet(request):
    """
    New technique description (the name is filled in on the edit page)
    """
    if request.method == 'POST' and 'delete' in request.POST:  # 'Delete' on an unsaved text = discard
        return redirect('snippet-list')
    form = TextSnippetForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        snippet = form.save()
        messages.success(request, f'"{snippet.name}" added to the text library.')
        return redirect('snippet-list')
    return render(request, 'reports/edit_snippet.html', {'form': form, 'snippet': None})


def edit_snippet(request, pk):
    """
    Edit a single text library entry
    """
    snippet = get_object_or_404(TextSnippet, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            snippet.delete()
            messages.success(request, 'Text deleted.')
            return redirect('snippet-list')
        form = TextSnippetForm(request.POST, instance=snippet)
        if form.is_valid():
            form.save()
            messages.success(request, 'Text saved.')
            return redirect('snippet-list')
    else:
        form = TextSnippetForm(instance=snippet)
    return render(request, 'reports/edit_snippet.html', {'form': form, 'snippet': snippet})
