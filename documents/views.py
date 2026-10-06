import mimetypes
import os

from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .forms import ACCEPT, DocumentForm
from .models import FILE_TYPES, Document, file_type_of

# Per library: its list and edit URL names, page title, the noun for one document and the empty-state icon
LIBRARIES = {
    Document.PROCEDURE: {'list': 'procedure-list', 'edit': 'edit-procedure',
                         'title': 'Procedures', 'noun': 'procedure', 'icon': Document.ICONS[Document.PROCEDURE]},
    Document.CODE: {'list': 'code-material-list', 'edit': 'edit-code-material',
                    'title': 'Code Material', 'noun': 'document', 'icon': Document.ICONS[Document.CODE]},
    Document.TRAINING: {'list': 'training-material-list', 'edit': 'edit-training-material',
                        'title': 'Training Material', 'noun': 'document', 'icon': Document.ICONS[Document.TRAINING]},
    Document.FORM: {'list': 'report-form-list', 'edit': 'edit-report-form',
                    'title': 'Report Forms', 'noun': 'form', 'icon': Document.ICONS[Document.FORM]},
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
    return render(request, 'documents/document_list.html',
                  {'items': documents, 'library': library, 'accept': ACCEPT})


def upload(request, category):
    """Saves each PDF, Word or Excel file as a document titled after its file name; anything else is skipped."""
    files = request.FILES.getlist('files')
    if not files:
        messages.error(request, 'Choose one or more files to upload.')
        return
    added, skipped = 0, []
    for uploaded in files:
        if not file_type_of(uploaded.name):
            skipped.append(uploaded.name)
            continue
        Document.objects.create(category=category, title=os.path.splitext(uploaded.name)[0], file=uploaded)
        added += 1
    if added:
        messages.success(request, f'Uploaded {added} file{"" if added == 1 else "s"}.')
    if skipped:
        messages.warning(request, f'Skipped (not a PDF, Word or Excel file): {", ".join(skipped)}.')


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


def open_document(request, pk):
    """
    Shows a PDF in the browser, or downloads a Word / Excel file for Office to open, and records
    it as just used (the dashboard lists by last use).
    """
    document = get_object_or_404(Document, pk=pk)
    Document.objects.filter(pk=pk).update(last_opened_at=timezone.now())
    content_type = mimetypes.guess_type(document.filename)[0] or 'application/octet-stream'
    return FileResponse(document.file.open('rb'), filename=document.filename, content_type=content_type,
                        as_attachment=document.file_type != 'pdf')


DASHBOARD_COUNT = 10


def dashboard_documents(query='', file_type=''):
    """
    The dashboard's Documentation card: every match for `query` and / or `file_type` ('pdf',
    'word', 'excel'), or with neither the 10 most recently used.
    """
    documents = Document.objects.recently_used()
    if not query.strip() and file_type not in FILE_TYPES:
        return documents[:DASHBOARD_COUNT]
    return documents.search(query).of_type(file_type)


def dashboard_context(request):
    """The Documentation card's template context, from its ?q= search and ?type= filter."""
    query, file_type = request.GET.get('q', ''), request.GET.get('type', '')
    return {'documents': dashboard_documents(query, file_type), 'query': query, 'file_type': file_type,
            'file_types': [(key, label) for key, (label, _, _) in FILE_TYPES.items()]}


def document_search(request):
    """The Documentation card's list for the search box and type filter (an HTML fragment)."""
    return render(request, 'documents/_dashboard_items.html', dashboard_context(request))
