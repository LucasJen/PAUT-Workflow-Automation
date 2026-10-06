import os

from django import forms

from reports.forms import StyledFormMixin
from .models import Document


def is_pdf(name):
    return os.path.splitext(name)[1].lower() == '.pdf'


def check_pdf(uploaded):
    if not is_pdf(uploaded.name):
        raise forms.ValidationError(f'{uploaded.name} is not a PDF.')


class DocumentForm(StyledFormMixin, forms.ModelForm):
    replace_file = forms.FileField(label='Replace PDF', required=False, validators=[check_pdf],
                                   widget=forms.FileInput(attrs={'accept': '.pdf,application/pdf'}),
                                   help_text='Leave empty to keep the current file.')

    class Meta:
        model = Document
        fields = ['title', 'notes']

    def save(self, commit=True):
        document = super().save(commit=False)
        replacement = self.cleaned_data.get('replace_file')
        old_name = document.file.name
        if replacement:
            document.file = replacement
        if commit:
            document.save()
            if replacement and old_name:
                document.file.storage.delete(old_name)
        return document
