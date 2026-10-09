import os

from django.db import models
from django.db.models.functions import Coalesce


# The file types a library takes: key -> (label, icon, extensions)
FILE_TYPES = {
    'pdf': ('PDF', 'file-earmark-pdf', ('.pdf',)),
    'word': ('Word', 'file-earmark-word', ('.doc', '.docx', '.docm')),
    'excel': ('Excel', 'file-earmark-excel', ('.xls', '.xlsx', '.xlsm')),
}
EXTENSIONS = {ext: key for key, (_, _, exts) in FILE_TYPES.items() for ext in exts}


def file_type_of(name):
    """'pdf', 'word' or 'excel' for a file name, or None for any other file."""
    return EXTENSIONS.get(os.path.splitext(name)[1].lower())


def file_type_q(key):
    """Matches documents whose file is of type `key`."""
    q = models.Q(pk__in=[])
    for ext in FILE_TYPES[key][2]:
        q |= models.Q(file__iendswith=ext)
    return q


class DocumentQuerySet(models.QuerySet):
    def recently_used(self):
        """Most recently opened first; a document never opened counts from its upload."""
        return self.order_by(Coalesce('last_opened_at', 'uploaded_at').desc(), '-pk')

    def search(self, query):
        """
        Documents whose title, description, file name, notes, library or file type (PDF / Word / Excel) contain
        every word of `query`.
        """
        labels = dict(Document.CATEGORY_CHOICES)
        result = self
        for word in query.split():
            in_label = [key for key, label in labels.items() if word.lower() in label.lower()]
            match = (models.Q(title__icontains=word) | models.Q(description__icontains=word)
                     | models.Q(file__icontains=word)
                     | models.Q(notes__icontains=word) | models.Q(category__in=in_label))
            for key, (label, _, _) in FILE_TYPES.items():
                if word.lower() in label.lower():
                    match |= file_type_q(key)
            result = result.filter(match)
        return result

    def of_type(self, key):
        """Only `key` ('pdf', 'word', 'excel') files; any other key keeps every document."""
        return self.filter(file_type_q(key)) if key in FILE_TYPES else self


class Document(models.Model):
    """A PDF, Word or Excel file kept in one of the documentation libraries (procedures, code / training material, report forms)."""
    PROCEDURE = 'procedure'
    CODE = 'code'
    TRAINING = 'training'
    FORM = 'form'
    CATEGORY_CHOICES = [
        (PROCEDURE, 'Procedures'),
        (CODE, 'Code Material'),
        (TRAINING, 'Training Material'),
        (FORM, 'Report Forms'),
    ]

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=255)
    # What the document is, in full: a procedure's title from its cover (e.g. 'Ultrasonic Examination of Welds ...')
    description = models.CharField(max_length=300, blank=True)
    file = models.FileField(upload_to='documents/%Y/', max_length=255)
    # The current file's revision, as the document names it (e.g. 'Rev. 3'); older files are kept as DocumentRevisions
    revision = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    last_opened_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    ICONS = {PROCEDURE: 'journal-check', CODE: 'book', TRAINING: 'mortarboard', FORM: 'clipboard-check'}

    @property
    def icon(self):
        return self.ICONS[self.category]

    @property
    def file_type(self):
        return file_type_of(self.file.name)

    @property
    def file_type_label(self):
        return FILE_TYPES[self.file_type][0] if self.file_type else ''

    @property
    def file_type_icon(self):
        return FILE_TYPES[self.file_type][1] if self.file_type else 'file-earmark'

    @property
    def last_used_at(self):
        return self.last_opened_at or self.uploaded_at

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    def delete(self, *args, **kwargs):
        # Removes the file, and its earlier revisions' files, from media/ along with the record
        storage = self.file.storage
        names = [self.file.name, *self.revisions.values_list('file', flat=True)]
        result = super().delete(*args, **kwargs)
        for name in names:
            if name:
                storage.delete(name)
        return result


class DocumentRevision(models.Model):
    """An earlier file of a document, kept when Replace file put a new one in its place (controlled procedures)."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='revisions')
    file = models.FileField(upload_to='documents/%Y/', max_length=255)
    revision = models.CharField(max_length=50, blank=True)
    replaced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-replaced_at', '-pk']

    def __str__(self):
        return f'{self.document} {self.revision}'.strip()

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    @property
    def file_type(self):
        return file_type_of(self.file.name)
