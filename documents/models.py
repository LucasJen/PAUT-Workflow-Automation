import os

from django.db import models
from django.db.models.functions import Coalesce


class DocumentQuerySet(models.QuerySet):
    def recently_used(self):
        """Most recently opened first; a document never opened counts from its upload."""
        return self.order_by(Coalesce('last_opened_at', 'uploaded_at').desc(), '-pk')

    def search(self, query):
        """Documents whose title, file name, notes or library name contain every word of `query`."""
        labels = dict(Document.CATEGORY_CHOICES)
        result = self
        for word in query.split():
            in_label = [key for key, label in labels.items() if word.lower() in label.lower()]
            result = result.filter(models.Q(title__icontains=word) | models.Q(file__icontains=word)
                                   | models.Q(notes__icontains=word) | models.Q(category__in=in_label))
        return result


class Document(models.Model):
    """A PDF kept in one of the documentation libraries (procedures, code material, training material)."""
    PROCEDURE = 'procedure'
    CODE = 'code'
    TRAINING = 'training'
    CATEGORY_CHOICES = [
        (PROCEDURE, 'Procedures'),
        (CODE, 'Code Material'),
        (TRAINING, 'Training Material'),
    ]

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to='documents/%Y/', max_length=255)
    notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    last_opened_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    ICONS = {PROCEDURE: 'journal-check', CODE: 'book', TRAINING: 'mortarboard'}

    @property
    def icon(self):
        return self.ICONS[self.category]

    @property
    def last_used_at(self):
        return self.last_opened_at or self.uploaded_at

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    def delete(self, *args, **kwargs):
        # Removes the PDF from media/ along with the record
        storage, name = self.file.storage, self.file.name
        result = super().delete(*args, **kwargs)
        if name:
            storage.delete(name)
        return result
