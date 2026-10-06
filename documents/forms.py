from django import forms

from reports.forms import StyledFormMixin
from .models import EXTENSIONS, Document, file_type_of


# For <input accept>: every extension a library takes
ACCEPT = ','.join(EXTENSIONS)


def check_file_type(uploaded):
    if not file_type_of(uploaded.name):
        raise forms.ValidationError(f'{uploaded.name} is not a PDF, Word or Excel file.')


class DocumentForm(StyledFormMixin, forms.ModelForm):
    replace_file = forms.FileField(label='Replace file', required=False, validators=[check_file_type],
                                   widget=forms.FileInput(attrs={'accept': ACCEPT}),
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
