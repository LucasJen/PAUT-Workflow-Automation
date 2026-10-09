"""Guided Creation with a job folder: existing or new; confirm; the report; downloads saved into the folder."""
import copy
import os
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from equipment.models import SensitivityBlock
from reports.models import Report, Setup, WorkingFolder
from reports.tests.test_nde_upload import FIXTURE, make_nde, sample_setup
from reports.views.reports import _duplicate_report


def nde_bytes(wall_in=0.237, offset_m=-0.0089):
    """A job .nde (the MXU fixture) scanned as a plate of this wall, like every real file."""
    setup = sample_setup()
    setup['specimens'][0]['plateGeometry']['thickness'] = wall_in * 0.0254
    for wedge in setup.get('wedges') or []:
        wedge.setdefault('positioning', {})['vCoordinateOffset'] = offset_m
    return make_nde(setup, copy.deepcopy(FIXTURE['properties']))


class GuidedCreationFolderTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.override = override_settings(REPORT_OUTPUT_DIR=None)
        self.override.enable()
        WorkingFolder.objects.all().delete()   # the migration's (this PC's 001 Welds)
        self.working = WorkingFolder.objects.create(path=str(self.root), report_type='paut_weld', is_default=True)

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()

    def job(self, name, files):
        folder = self.root / name
        folder.mkdir()
        for file_name in files:
            (folder / file_name).write_bytes(nde_bytes())
        return folder

    def test_existing_folder_gives_the_name_and_client_and_reads_files_in_place(self):
        folder = self.job('FHR-32-27119-FW6-4in', ['32-27119 fw6 off1.nde', '32-27119 fw6 off2.nde'])
        page = self.client.get(reverse('start-from-files'))
        self.assertContains(page, 'FHR-32-27119-FW6-4in')
        self.assertContains(page, 'FHR · Flint Hills Resources')

        resp = self.client.post(reverse('start-from-files'), {
            'folder_mode': 'existing', 'job_folder': 'FHR-32-27119-FW6-4in', 'units': 'imperial'})
        self.assertRedirects(resp, reverse('confirm-job'))
        page = self.client.get(reverse('confirm-job'))
        # The NPS / Sch isn't picked for you (not from the folder name, not from the files): only the wall is shown
        self.assertNotContains(page, ' selected>')
        self.assertContains(page, 'Pick the NPS / Sch…')
        self.assertContains(page, 'The files\' wall: 0.237"')
        self.assertContains(page, 'value="FHR-32-27119-FW6-4in"')
        self.assertContains(page, 'Client Flint Hills Resources')

        data = {'document_filename': 'FHR-32-27119-FW6-4in', 'sensitivity_block': '', 'include_0': '1',
                'include_1': '1', 'weld_0': 'FW6', 'weld_1': 'FW6'}
        self.assertContains(self.client.post(reverse('confirm-job'), data), 'Pick the NPS / Sch.')
        self.assertFalse(Report.objects.exists())
        block = SensitivityBlock.objects.get(pipe_size='4in Sch 40')
        self.client.post(reverse('confirm-job'), {**data, 'sensitivity_block': block.pk})
        report = Report.objects.get()
        self.assertEqual((report.document_filename, report.client, report.location, report.sensitivity_block,
                          report.job_folder), ('FHR-32-27119-FW6-4in', 'Flint Hills Resources', 'Rosemount, MN',
                                               block, str(folder)))
        self.assertEqual(sorted(os.listdir(folder)), ['32-27119 fw6 off1.nde', '32-27119 fw6 off2.nde'])

    def test_a_file_without_a_weld_name_gets_the_folders_weld_and_others_are_flagged(self):
        self.job('PPI-32-27119-FW6-4in', ['scan a.nde', 'ppi 32-27119 fw9 off1.nde'])
        self.client.post(reverse('start-from-files'), {'folder_mode': 'existing', 'job_folder': 'PPI-32-27119-FW6-4in'})
        page = self.client.get(reverse('confirm-job'))
        self.assertContains(page, 'name="weld_1" value="FW6"')    # 'scan a.nde' (sorted after the named one)
        self.assertContains(page, 'Not in the folder name (FW6)')  # fw9
        self.assertContains(page, 'Preferences › Client codes</a> yet')   # PPI has no client code yet

    def test_new_folder_is_made_with_the_typed_name_and_gets_the_uploads(self):
        resp = self.client.post(reverse('start-from-files'), {
            'folder_mode': 'new', 'new_name': ' FHR-75-62816-FW3&5-4in ', 'nde_files': [SimpleUploadedFile('FHR 75-62816 FW3 OFF1.nde', nde_bytes()),
                                          SimpleUploadedFile('FHR 75-62816 FW5 OFF1.nde', nde_bytes())]})
        self.assertRedirects(resp, reverse('confirm-job'))
        folder = self.root / 'FHR-75-62816-FW3&5-4in'
        self.assertEqual(sorted(os.listdir(folder)), ['FHR 75-62816 FW3 OFF1.nde', 'FHR 75-62816 FW5 OFF1.nde'])
        block = SensitivityBlock.objects.get(pipe_size='4in Sch 40')
        self.client.post(reverse('confirm-job'), {'document_filename': folder.name, 'include_0': '1', 'include_1': '1',
                                                  'weld_0': 'FW3', 'weld_1': 'FW5', 'sensitivity_block': block.pk})
        self.assertEqual(Report.objects.get().job_folder, str(folder))

    def test_problems_stay_on_the_first_page(self):
        self.job('PPI-1-2-W1-2in', [])
        cases = [
            ({'folder_mode': 'existing'}, 'Pick a job folder'),
            ({'folder_mode': 'existing', 'job_folder': '..'}, 'Pick a job folder'),
            ({'folder_mode': 'new', 'new_name': ''}, 'Type the new folder'),
            ({'folder_mode': 'new', 'new_name': 'PPI-32/27119'}, 'characters a folder name can'),
            ({'folder_mode': 'new', 'new_name': 'PPI-1-3-W1-2in'}, 'files to copy into the new folder'),
            ({'folder_mode': 'existing', 'job_folder': 'PPI-1-2-W1-2in'}, 'has no .nde files yet'),
        ]
        for data, message in cases:
            with self.subTest(message):
                resp = self.client.post(reverse('start-from-files'), data, follow=True)
                self.assertContains(resp, message)
                self.assertIsNone(self.client.session.get('job_import'))
        self.assertEqual(os.listdir(self.root), ['PPI-1-2-W1-2in'])   # nothing made on a failed new folder

    def test_downloads_save_into_the_folder_without_replacing_files_the_app_didnt_write(self):
        folder = self.job('FHR-94-35832-W14-3in', [])
        (folder / 'FHR-94-35832-W14-3in.docx').write_bytes(b'made by hand')
        report = Report.objects.create(document_filename='FHR-94-35832-W14-3in', job_folder=str(folder))
        Setup.objects.create(report=report)
        for _ in range(2):   # the second download replaces the app's own copy
            resp = self.client.get(reverse('generate-report', args=[report.pk]))
            self.assertEqual(resp.status_code, 200)
            b''.join(resp.streaming_content)
        self.assertEqual((folder / 'FHR-94-35832-W14-3in.docx').read_bytes(), b'made by hand')
        self.assertEqual(sorted(os.listdir(folder)), ['FHR-94-35832-W14-3in (2).docx', 'FHR-94-35832-W14-3in.docx'])
        report.refresh_from_db()
        self.assertEqual(report.job_folder_files, ['FHR-94-35832-W14-3in (2).docx'])

    def test_the_editor_keeps_the_folder_and_the_bar_can_change_or_clear_it(self):
        folder = self.job('PPI-27-66879-W2-8in', [])
        other = self.job('PPI-23-21092-W3&4-24in', [])
        report = Report.objects.create(report_type='paut_weld', document_filename='x', job_folder=str(folder),
                                       job_folder_files=['x.xlsx'])
        page = self.client.get(f"{reverse('create-report')}?loaded={report.pk}")
        self.assertContains(page, 'downloads are saved here too')
        url = reverse('report-job-folder', args=[report.pk])
        self.client.post(url, {'action': 'set', 'job_folder': other.name})
        report.refresh_from_db()
        self.assertEqual((report.job_folder, report.job_folder_files), (str(other), []))
        self.client.post(url, {'action': 'set', 'job_folder': 'nope'})
        report.refresh_from_db()
        self.assertEqual(report.job_folder, str(other))
        self.client.post(url, {'action': 'clear'})
        report.refresh_from_db()
        self.assertEqual(report.job_folder, '')

    def test_a_duplicate_starts_without_the_folder(self):
        report = Report.objects.create(document_filename='x', job_folder=str(self.root), job_folder_files=['x.xlsx'])
        duplicate = _duplicate_report(report)
        self.assertEqual((duplicate.job_folder, duplicate.job_folder_files), ('', []))

    def test_the_page_uses_the_types_default_working_folder_and_cant_change_it(self):
        other_root = self.root / 'Other welds'
        other_root.mkdir()
        (other_root / 'PPI-9-9-W9-2in').mkdir()
        other = WorkingFolder.objects.create(path=str(other_root), report_type='paut_weld')
        self.job('FHR-1-1-W1-2in', [])
        page = self.client.get(reverse('start-from-files'), {'root': other.pk})   # ignored
        self.assertContains(page, 'FHR-1-1-W1-2in')
        self.assertNotContains(page, 'PPI-9-9-W9-2in')
        self.assertContains(page, 'Change in Preferences › Working folders')
        self.assertNotContains(page, 'data-browse-for')
        # Posting a folder from another working folder doesn't reach it
        resp = self.client.post(reverse('start-from-files'), {
            'root': other.pk, 'folder_mode': 'existing', 'job_folder': 'PPI-9-9-W9-2in'}, follow=True)
        self.assertContains(resp, 'Pick a job folder')
        self.client.post(reverse('start-from-files'), {'add_root': '1', 'root_path': str(other_root), 'root_default': '1'})
        self.assertEqual(WorkingFolder.objects.get(is_default=True, report_type='paut_weld'), self.working)

    def test_without_a_working_folder_the_page_asks_for_one(self):
        WorkingFolder.objects.all().delete()
        page = self.client.get(reverse('start-from-files'))
        self.assertContains(page, 'none set for PAUT weld (Excel) reports')
        resp = self.client.post(reverse('start-from-files'), {'folder_mode': 'existing', 'job_folder': 'x'}, follow=True)
        self.assertContains(resp, 'Set a working folder for these reports in Preferences')

    def test_the_report_type_picks_the_working_folders_and_only_guided_types_go_on(self):
        hic_root = self.root / 'HIC jobs'
        hic_root.mkdir()
        WorkingFolder.objects.create(path=str(hic_root), report_type='paut_long')
        page = self.client.get(reverse('start-from-files'))
        self.assertContains(page, '<option value="paut_weld" selected>PAUT weld (Excel)</option>', html=True)
        self.assertNotContains(page, 'guided workflow coming later')   # every type is guided now
        self.assertContains(page, 'id="start-form"')

        page = self.client.get(reverse('start-from-files'), {'type': 'paut_long'})
        self.assertContains(page, str(hic_root))
        self.assertNotContains(page, 'FHR-1-1-W1-2in')
        self.assertContains(page, 'id="start-form"')

        self.assertEqual(self.client.get(reverse('start-from-files'), {'type': 'bogus'}).context['rtype'].key, 'paut_weld')
