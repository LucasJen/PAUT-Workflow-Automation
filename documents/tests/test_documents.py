"""Documentation libraries: bulk PDF upload, replace and delete."""
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from documents.models import Document

PDF = b'%PDF-1.4\n%%EOF\n'


def pdf(name):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


class DocumentLibraryTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_bulk_upload_titles_after_file_names_and_skips_non_pdfs(self):
        txt = SimpleUploadedFile('notes.txt', b'hi', content_type='text/plain')
        response = self.client.post(reverse('procedure-list'), {
            'upload': '1', 'files': [pdf('PAUT-001 Rev 3.pdf'), pdf('PAUT-002.PDF'), txt]}, follow=True)
        titles = list(Document.objects.values_list('category', 'title'))
        self.assertEqual(titles, [('procedure', 'PAUT-001 Rev 3'), ('procedure', 'PAUT-002')])
        self.assertContains(response, 'Uploaded 2 PDFs.')
        self.assertContains(response, 'Skipped (not a PDF): notes.txt.')

    def test_each_library_lists_only_its_own_documents(self):
        self.client.post(reverse('code-material-list'), {'upload': '1', 'files': [pdf('ASME V.pdf')]})
        self.client.post(reverse('training-material-list'), {'upload': '1', 'files': [pdf('Level II.pdf')]})
        code = self.client.get(reverse('code-material-list'))
        self.assertContains(code, 'ASME V')
        self.assertNotContains(code, 'Level II')
        doc = Document.objects.get(title='ASME V')
        self.assertEqual(self.client.get(reverse('edit-training-material', args=[doc.pk])).status_code, 404)

    def test_replace_and_delete_remove_the_old_file(self):
        self.client.post(reverse('procedure-list'), {'upload': '1', 'files': [pdf('old.pdf')]})
        doc = Document.objects.get()
        old_path = doc.file.path
        self.client.post(reverse('edit-procedure', args=[doc.pk]),
                         {'title': 'Renamed', 'notes': '', 'replace_file': pdf('new.pdf')})
        doc.refresh_from_db()
        self.assertEqual((doc.title, doc.filename), ('Renamed', 'new.pdf'))
        self.assertFalse(os.path.exists(old_path))
        new_path = doc.file.path
        self.client.post(reverse('procedure-list'), {'delete': '1', 'selected': [doc.pk]})
        self.assertFalse(Document.objects.exists())
        self.assertFalse(os.path.exists(new_path))

    def test_replacement_must_be_a_pdf(self):
        self.client.post(reverse('procedure-list'), {'upload': '1', 'files': [pdf('a.pdf')]})
        doc = Document.objects.get()
        response = self.client.post(reverse('edit-procedure', args=[doc.pk]), {
            'title': 'a', 'replace_file': SimpleUploadedFile('a.docx', b'x')})
        self.assertContains(response, 'a.docx is not a PDF.')
