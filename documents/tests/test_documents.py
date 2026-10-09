"""Documentation libraries: bulk PDF / Word / Excel upload, open, replace and delete; the dashboard card."""
import os
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from documents.models import Document

PDF = b'%PDF-1.4\n%%EOF\n'


def pdf(name):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


def office(name):
    return SimpleUploadedFile(name, b'PK\x03\x04', content_type='application/octet-stream')


class DocumentLibraryTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_bulk_upload_takes_pdf_word_and_excel_and_skips_anything_else(self):
        txt = SimpleUploadedFile('notes.txt', b'hi', content_type='text/plain')
        response = self.client.post(reverse('procedure-list'), {'upload': '1', 'files': [
            pdf('PAUT-001 Rev 3.pdf'), pdf('PAUT-002.PDF'), office('Checklist.docx'), office('Old.doc'),
            office('Log.xlsx'), office('Macro sheet.xlsm'), txt]}, follow=True)
        docs = {d.title: d.file_type for d in Document.objects.filter(category=Document.PROCEDURE)}
        self.assertEqual(docs, {'PAUT-001 Rev 3': 'pdf', 'PAUT-002': 'pdf', 'Checklist': 'word', 'Old': 'word',
                                'Log': 'excel', 'Macro sheet': 'excel'})
        self.assertContains(response, 'Uploaded 6 files.')
        self.assertContains(response, 'Skipped (not a PDF, Word or Excel file): notes.txt.')
        self.assertContains(response, 'file-earmark-word')

    def test_pdfs_open_in_the_browser_and_office_files_download(self):
        self.client.post(reverse('report-form-list'), {'upload': '1', 'files': [pdf('a.pdf'), office('b.xlsx')]})
        opened = {}
        for doc in Document.objects.all():
            response = self.client.get(reverse('open-document', args=[doc.pk]))
            opened[doc.title] = (response['Content-Type'], response['Content-Disposition'].split(';')[0])
            response.close()
        self.assertEqual(opened, {
            'a': ('application/pdf', 'inline'),
            'b': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'attachment')})

    def test_a_document_whose_file_is_missing_says_so(self):
        import os
        self.client.post(reverse('procedure-list'), {'upload': '1', 'files': [pdf('gone.pdf')]})
        doc = Document.objects.get()
        os.remove(doc.file.path)
        response = self.client.get(reverse('open-document', args=[doc.pk]), follow=True)
        self.assertRedirects(response, reverse('edit-procedure', args=[doc.pk]))
        self.assertContains(response, 'is missing from the library')
        doc.refresh_from_db()
        self.assertIsNone(doc.last_opened_at)

    def test_each_library_lists_only_its_own_documents(self):
        self.client.post(reverse('code-material-list'), {'upload': '1', 'files': [pdf('ASME V.pdf')]})
        self.client.post(reverse('training-material-list'), {'upload': '1', 'files': [pdf('Level II.pdf')]})
        code = self.client.get(reverse('code-material-list'))
        self.assertContains(code, 'ASME V')
        self.assertNotContains(code, 'Level II')
        doc = Document.objects.get(title='ASME V')
        self.assertEqual(self.client.get(reverse('edit-training-material', args=[doc.pk])).status_code, 404)

    def test_report_forms_library(self):
        self.client.post(reverse('report-form-list'), {'upload': '1', 'files': [pdf('Weld form.pdf')]})
        doc = Document.objects.get()
        self.assertEqual(doc.category, Document.FORM)
        self.assertContains(self.client.get(reverse('report-form-list')), 'Weld form')
        self.assertEqual(self.client.get(reverse('edit-report-form', args=[doc.pk])).status_code, 200)

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

    def test_description_column_edited_on_the_edit_page_and_searchable(self):
        self.client.post(reverse('procedure-list'), {'upload': '1', 'files': [pdf('100-UT-001.pdf')]})
        doc = Document.objects.get()
        self.assertEqual(doc.description, '')     # not read from the file
        title = 'Ultrasonic Examination of Welds in Accordance with ASME Section V, Article 4 (Welds)'
        self.client.post(reverse('edit-procedure', args=[doc.pk]),
                         {'title': '100-UT-001', 'description': title, 'notes': ''})
        page = self.client.get(reverse('procedure-list'))
        self.assertContains(page, '>Description<')
        self.assertContains(page, title)
        self.assertEqual(list(Document.objects.search('ASME Article 4')), [doc])

    def test_replacement_must_be_pdf_word_or_excel(self):
        self.client.post(reverse('procedure-list'), {'upload': '1', 'files': [pdf('a.pdf')]})
        doc = Document.objects.get()
        response = self.client.post(reverse('edit-procedure', args=[doc.pk]), {
            'title': 'a', 'replace_file': SimpleUploadedFile('a.txt', b'x')})
        self.assertContains(response, 'a.txt is not a PDF, Word or Excel file.')
        self.client.post(reverse('edit-procedure', args=[doc.pk]), {'title': 'a', 'replace_file': office('a.docx')})
        doc.refresh_from_db()
        self.assertEqual(doc.file_type, 'word')


class DashboardDocumentsTests(TestCase):
    """The dashboard's Documentation card: most recently used first, 10 by default, searchable."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def make(self, title, category=Document.PROCEDURE, hours_ago=0, opened_hours_ago=None, notes='', ext='.pdf'):
        now = timezone.now()
        doc = Document.objects.create(category=category, title=title, file=pdf(f'{title}{ext}'), notes=notes)
        Document.objects.filter(pk=doc.pk).update(
            uploaded_at=now - timedelta(hours=hours_ago),
            last_opened_at=None if opened_hours_ago is None else now - timedelta(hours=opened_hours_ago))
        return doc

    def titles(self, response):
        return [d.title for d in response.context['documents']]

    def test_most_recently_used_first_across_all_libraries(self):
        self.make('Uploaded long ago, opened just now', Document.TRAINING, hours_ago=100, opened_hours_ago=0)
        self.make('Uploaded an hour ago', Document.CODE, hours_ago=1)
        self.make('Opened yesterday', hours_ago=50, opened_hours_ago=24)
        response = self.client.get(reverse('home'))
        self.assertEqual(self.titles(response), [
            'Uploaded long ago, opened just now', 'Uploaded an hour ago', 'Opened yesterday'])
        self.assertNotContains(response, 'Calibration due')

    def test_only_the_10_most_recent_by_default_but_search_returns_every_match(self):
        for n in range(12):
            self.make(f'Procedure {n:02}', hours_ago=n)
        self.assertEqual(self.titles(self.client.get(reverse('home'))), [f'Procedure {n:02}' for n in range(10)])
        response = self.client.get(reverse('document-search'), {'q': 'procedure'})
        self.assertEqual(len(response.context['documents']), 12)

    def test_search_matches_title_notes_file_name_and_library(self):
        self.make('PAUT-001', notes='Girth welds')
        self.make('ASME V Article 4', Document.CODE)
        self.make('Level II course', Document.TRAINING)
        self.make('Weld inspection form', Document.FORM)
        search = lambda q: [d.title for d in self.client.get(reverse('document-search'), {'q': q}).context['documents']]
        self.assertEqual(search('girth'), ['PAUT-001'])
        self.assertEqual(search('asme article'), ['ASME V Article 4'])
        self.assertEqual(search('training'), ['Level II course'])
        self.assertEqual(search('report forms'), ['Weld inspection form'])
        self.assertContains(self.client.get(reverse('document-search'), {'q': 'zzz'}), 'No documents match')

    def test_opening_a_document_serves_the_pdf_and_moves_it_to_the_top(self):
        old = self.make('Old', hours_ago=10)
        self.make('New', hours_ago=1)
        response = self.client.get(reverse('open-document', args=[old.pk]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(response.streaming_content), PDF)
        response.close()
        self.assertEqual(self.titles(self.client.get(reverse('home'))), ['Old', 'New'])

    def test_file_type_filter_alone_or_with_a_search(self):
        for n in range(12):
            self.make(f'Form {n:02}', Document.FORM, hours_ago=n, ext='.xlsx')
        self.make('Weld procedure', hours_ago=20, ext='.docx')
        self.make('Weld scan plan', hours_ago=21)
        filtered = lambda **params: [d.title for d in
                                     self.client.get(reverse('document-search'), params).context['documents']]
        self.assertEqual(len(filtered(type='excel')), 12)          # a filter returns every match, not 10
        self.assertEqual(filtered(type='word'), ['Weld procedure'])
        self.assertEqual(filtered(q='weld', type='pdf'), ['Weld scan plan'])
        self.assertEqual(filtered(q='weld'), ['Weld procedure', 'Weld scan plan'])
        self.assertEqual(filtered(q='word'), ['Weld procedure'])   # the type name is searchable too
        self.assertEqual(len(filtered(type='bogus')), 10)          # an unknown type is ignored
        home = self.client.get(reverse('home'), {'type': 'word'})
        self.assertEqual(self.titles(home), ['Weld procedure'])
        self.assertContains(home, '<option value="word" selected>')
