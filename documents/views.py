import os

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .forms import DocumentForm, is_pdf
from .models import Document

# Per library: its list and edit URL names, page title, the noun for one document and the empty-state icon
LIBRARIES = {
    Document.PROCEDURE: {'list': 'procedure-list', 'edit': 'edit-procedure',
                         'title': 'Procedures', 'noun': 'procedure', 'icon': 'journal-check'},
    Document.CODE: {'list': 'code-material-list', 'edit': 'edit-code-material',
                    'title': 'Code Material', 'noun': 'document', 'icon': 'book'},
    Document.TRAINING: {'list': 'training-material-list', 'edit': 'edit-training-material',
                        'title': 'Training Material', 'noun': 'document', 'icon': 'mortarboard'},
}


def document_list(request, category):
    library = LIBRARIES[category]
    documents = Document.objects.filter(category=category)
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'upload' in request.POST:
            upload(request, category)
            return redirect(library['list'])
        if 'delete' in request.POST:
            for document in documents.filter(pk__in=selected_pks):
                document.delete()
            return redirect(library['list'])
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect(library['edit'], pk=selected_pks[0])
    return render(request, 'documents/document_list.html', {'items': documents, 'library': library})


def upload(request, category):
    """Saves each uploaded PDF as a document titled after its file name; anything else is skipped."""
    files = request.FILES.getlist('files')
    if not files:
        messages.error(request, 'Choose one or more PDFs to upload.')
        return
    added, skipped = 0, []
    for uploaded in files:
        if not is_pdf(uploaded.name):
            skipped.append(uploaded.name)
            continue
        Document.objects.create(category=category, title=os.path.splitext(uploaded.name)[0], file=uploaded)
        added += 1
    if added:
        messages.success(request, f'Uploaded {added} PDF{"" if added == 1 else "s"}.')
    if skipped:
        messages.warning(request, f'Skipped (not a PDF): {", ".join(skipped)}.')


def edit_document(request, category, pk):
    library = LIBRARIES[category]
    document = get_object_or_404(Document, pk=pk, category=category)
    noun = library['noun'].capitalize()
    if request.method == 'POST':
        if 'delete' in request.POST:
            document.delete()
            messages.success(request, f'{noun} deleted.')
            return redirect(library['list'])
        form = DocumentForm(request.POST, request.FILES, instance=document)
        if form.is_valid():
            form.save()
            messages.success(request, f'{noun} saved.')
            return redirect(library['list'])
    else:
        form = DocumentForm(instance=document)
    return render(request, 'documents/edit_document.html',
                  {'form': form, 'document': document, 'library': library})
