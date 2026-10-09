"""Guided Creation for the corrosion form: a job folder's .nde files and pictures to a report."""
from datetime import date
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from equipment.models import ProbeModel
from reports.models import Report, ReportImage, WorkingFolder
from reports.services.corrosion_import import (
    DRAWING, IMAGE, SETUP, build_corrosion_report, caption_for, equipment_from_folder, guess_role,
)
from reports.tests.test_job_folder_flow import nde_bytes


def png(size=(200, 120), fmt='PNG'):
    buf = BytesIO()
    Image.new('RGB', size, 'white').save(buf, fmt)
    return buf.getvalue()


class GuessTests(TestCase):
    def test_what_a_folder_picture_is(self):
        self.assertEqual(guess_role('04-30--11V58A.jpg'), DRAWING)
        self.assertEqual(guess_role('11V-2 Model (1).png'), DRAWING)
        self.assertEqual(guess_role('Screenshot 2026-03-11 100904.png'), SETUP)
        self.assertEqual(guess_role('strip scan top head.png'), IMAGE)
        self.assertEqual(caption_for('strip scan top head.png'), 'Strip scan top head')
        self.assertEqual(equipment_from_folder('11V58A Corrosion Scan'), '11V58A')
        self.assertEqual(equipment_from_folder('86TK116 Corrosion Scans'), '86TK116')



class ScanDateTests(TestCase):
    def test_scan_dates_in_other_forms_are_left_out(self):
        from reports.services.corrosion_import import scan_date
        self.assertEqual(scan_date('2026-03-11 10:09'), date(2026, 3, 11))
        self.assertIsNone(scan_date('3/11/2026 10:09 AM'))
        self.assertIsNone(scan_date(''))
        files = [{'filename': 'a.nde', 'scan_time': '3/11/2026', 'setups': [{'label': 'G1', 'values': {}}]},
                 {'filename': 'b.nde', 'scan_time': '2026-03-12 08:00', 'setups': [{'label': 'G1', 'values': {}}]}]
        report, _ = build_corrosion_report(files, [])
        self.assertEqual(report.test_date, date(2026, 3, 12))


class CorrosionGuidedTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media, REPORT_OUTPUT_DIR=None)
        self.override.enable()
        WorkingFolder.objects.all().delete()
        WorkingFolder.objects.create(path=str(self.root), report_type='paut_corrosion', is_default=True)

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()
        shutil.rmtree(self.media, ignore_errors=True)

    def job(self, name, files):
        folder = self.root / name
        folder.mkdir()
        for file_name, content in files.items():
            (folder / file_name).write_bytes(content)
        return folder

    def start(self, **data):
        return self.client.post(reverse('start-from-files'), {'type': 'paut_corrosion', **data})

    def test_a_folder_with_files_and_pictures(self):
        folder = self.job('11V58B Corrosion Scan', {
            '11v58b shell.nde': nde_bytes(), '11v58b head.nde': nde_bytes(),
            '04-30--11V58B.jpg': png((300, 200), 'JPEG'), 'Screenshot 1.png': png(), 'strip scan shell.png': png(),
            'notes.txt': b'x'})
        page = self.client.get(reverse('start-from-files'), {'type': 'paut_corrosion'})
        self.assertContains(page, '11V58B Corrosion Scan')
        self.assertContains(page, '3 pictures')
        self.assertNotContains(page, 'id="start-block"')    # no NPS / Sch for this form

        self.assertRedirects(self.start(folder_mode='existing', job_folder=folder.name), reverse('confirm-job'))
        page = self.client.get(reverse('confirm-job'))
        self.assertContains(page, 'name="equipment_id" value="11V58B"')
        self.assertContains(page, 'value="11V58B Corrosion Scan"')
        self.assertContains(page, '1 setup page')   # both files: the same setup
        self.assertContains(page, '<option value="drawing" selected>Drawing</option>', html=True)
        self.assertContains(page, 'value="Strip scan shell"')
        picture_response = self.client.get(reverse('job-picture', args=[0]))
        self.assertEqual(picture_response.status_code, 200)
        picture_response.close()     # releases the file, which Windows otherwise keeps locked for the cleanup
        self.assertEqual(self.client.get(reverse('job-picture', args=[9])).status_code, 404)

        names = self.client.session['job_import']['pictures']
        self.assertEqual(names, ['04-30--11V58B.jpg', 'Screenshot 1.png', 'strip scan shell.png'])
        resp = self.client.post(reverse('confirm-job'), {
            'document_filename': '2026-10-PAUT-Corrosion-11V58B', 'equipment_id': '11V58B',
            'include_0': '1', 'include_1': '1',
            'role_0': 'drawing', 'role_1': 'setup', 'role_2': 'image', 'caption_2': 'Shell strip scan'})
        report = Report.objects.get()
        self.assertRedirects(resp, f"{reverse('create-report')}?loaded={report.pk}&wizard=1", fetch_redirect_response=False)
        self.assertEqual((report.report_type, report.document_filename, report.equipment_id, report.job_folder),
                         ('paut_corrosion', '2026-10-PAUT-Corrosion-11V58B', '11V58B', str(folder)))
        self.assertIsNotNone(report.test_date)
        setup = report.setups.get()
        # No guessed method: the technician picks the description (and so the Method) in the editor
        self.assertEqual((setup.title, setup.method_description, setup.images.count()), ('', None, 1))
        self.assertTrue(setup.scope_model)
        self.assertEqual(report.images.get(kind=ReportImage.DRAWING).caption, '')
        self.assertEqual(report.images.get(kind=ReportImage.SCAN).caption, 'Shell strip scan')
        self.assertIsNone(self.client.session.get('job_import'))

    def test_a_manual_ut_folder_without_files_gets_an_empty_setup(self):
        self.job('11V58A Corrosion Scan', {'04-30--11V58A.jpg': png((300, 200), 'JPEG')})
        self.assertRedirects(self.start(folder_mode='existing', job_folder='11V58A Corrosion Scan'), reverse('confirm-job'))
        self.assertContains(self.client.get(reverse('confirm-job')), 'No .nde files')
        resp = self.client.post(reverse('confirm-job'), {'document_filename': 'x', 'equipment_id': '11V58A'}, follow=True)
        self.assertContains(resp, 'one empty setup was added')
        report = Report.objects.get()
        self.assertEqual((report.setups.count(), report.images.count()), (1, 1))   # the .jpg guessed as the drawing

    def test_a_folder_named_with_a_client_code_gets_that_client(self):
        from reports.models import ClientCode
        ClientCode.objects.update_or_create(code='FHR', defaults={'client': 'Flint Hills Resources', 'location': 'Rosemount, MN'})
        self.job('FHR-86TK116 Corrosion Scans', {'a.png': png()})
        self.start(folder_mode='existing', job_folder='FHR-86TK116 Corrosion Scans')
        page = self.client.get(reverse('confirm-job'))
        self.assertContains(page, 'name="equipment_id" value="86TK116"')
        self.assertContains(page, 'Client Flint Hills Resources, Rosemount, MN (FHR).')
        self.client.post(reverse('confirm-job'), {'role_0': 'image', 'equipment_id': '86TK116'})
        report = Report.objects.get()
        self.assertEqual((report.client, report.location), ('Flint Hills Resources', 'Rosemount, MN'))

    def test_leaving_pictures_out_and_files_only(self):
        self.job('TK86-100 Corrosion Scans', {'a.png': png(), 'b.png': png()})
        self.start(folder_mode='existing', job_folder='TK86-100 Corrosion Scans')
        self.client.post(reverse('confirm-job'), {'role_0': 'skip', 'role_1': 'image', 'caption_1': 'B'})
        self.assertEqual(list(Report.objects.get().images.values_list('caption', flat=True)), ['B'])
        self.assertContains(self.start(folder_mode='none'), "Choose the job")   # files only needs files

    def test_catalogue_matches_link_the_setup(self):
        probe = ProbeModel.objects.create(model='TEST-PROBE-1')
        files = [{'filename': 'a.nde', 'setups': [{'label': 'G1', 'values': {
            'title': 'HydroFORM', 'transducer_model': '5L64-A2', 'catalogue_probe': probe.pk, 'catalogue_wedge': ''}}]}]
        report, _ = build_corrosion_report(files, [])
        self.assertEqual(report.report_date, date.today())   # as a new report in the editor
        setup = report.setups.get()
        self.assertEqual((setup.catalogue_probe, setup.catalogue_wedge), (probe, None))

    def test_the_weld_flow_is_unchanged(self):
        WorkingFolder.objects.create(path=str(self.root), report_type='paut_weld', is_default=True)
        page = self.client.get(reverse('start-from-files'))
        self.assertContains(page, 'id="start-block"')
