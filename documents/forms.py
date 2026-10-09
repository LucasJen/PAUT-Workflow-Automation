from django import forms

from reports.forms import StyledFormMixin
from .models import EXTENSIONS, Document, DocumentRevision, file_type_of


# For <input accept>: every extension a library takes
ACCEPT = ','.join(EXTENSIONS)


def check_file_type(uploaded):
    if not file_type_of(uploaded.name):
        raise forms.ValidationError(f'{uploaded.name} is not a PDF, Word or Excel file.')


class DocumentForm(StyledFormMixin, forms.ModelForm):
    replace_file = forms.FileField(label='Replace file', required=False, validators=[check_file_type],
                                   widget=forms.FileInput(attrs={'accept': ACCEPT}),
                                   help_text='The current file is kept in the revision history. '
                                             "Set Revision to the new file's.")

    class Meta:
        model = Document
        fields = ['title', 'description', 'revision', 'notes']
        help_texts = {'revision': 'e.g. Rev. 3'}

    def save(self, commit=True):
        document = super().save(commit=False)
        replacement = self.cleaned_data.get('replace_file')
        old_name, old_revision = document.file.name, self.initial.get('revision', '')
        if replacement:
            document.file = replacement
        if commit:
            document.save()
            if replacement and old_name:
                # The file it replaces stays, as an earlier revision
                DocumentRevision.objects.create(document=document, file=old_name, revision=old_revision)
        return document
