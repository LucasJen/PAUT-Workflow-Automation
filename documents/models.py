import os

from django.db import models


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

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

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
