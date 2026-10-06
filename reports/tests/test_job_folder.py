"""Job folders: reading their names, listing / resolving them; working folders; the folder dialog."""
import os
import tempfile
from pathlib import Path

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from reports.models import ClientCode, WorkingFolder
from reports.services.job_folder import (
    add_working_folder, invalid_name, job_folders, nde_files, parse_folder_name, pick_folder, resolve_job_folder,
    working_folder,
)

# Every job folder in Desktop\Reports\001 Welds (2026-10-06): (name, client, unit, line, welds, NPS)
REAL_FOLDERS = [
    ('FHR-101-44812-W1&2-2in', 'FHR', '101', '44812', ['W1', 'W2'], '2'),
    ('FHR-14-44929-W11,12,15,21-2in', 'FHR', '14', '44929', ['W11', 'W12', 'W15', 'W21'], '2'),
    ('FHR-23-22204-WP-10-3in', 'FHR', '23', '22204', ['WP10'], '3'),
    ('FHR-23-56351-2in-W5&30&34', 'FHR', '23', '56351', ['W5', 'W30', 'W34'], '2'),
    ('FHR-33-20654-W2-4in', 'FHR', '33', '20654', ['W2'], '4'),
    ('FHR-43-4110-FW16-2in', 'FHR', '43', '4110', ['FW16'], '2'),
    ('FHR-6302-W11-2in', 'FHR', '', '6302', ['W11'], '2'),
    ('FHR-75-62816-FW3&5-4in', 'FHR', '75', '62816', ['FW3', 'FW5'], '4'),
    ('FHR-75-62820-FW3&5-4in', 'FHR', '75', '62820', ['FW3', 'FW5'], '4'),
    ('FHR-94-35832-W14-3in', 'FHR', '94', '35832', ['W14'], '3'),
    ('FHR-94-43321-FW1.2-6in', 'FHR', '94', '43321', ['FW1', 'FW2'], '6'),
    ('PPI-00-11006-FW5-3in', 'PPI', '00', '11006', ['FW5'], '3'),
    ('PPI-00-67238-FW7-3in', 'PPI', '00', '67238', ['FW7'], '3'),
    ('PPI-00-67239-FW5-3in', 'PPI', '00', '67239', ['FW5'], '3'),
    ('PPI-01-53812-FW6,7-6in', 'PPI', '01', '53812', ['FW6', 'FW7'], '6'),
    ('PPI-01-66773-FW12-12in', 'PPI', '01', '66773', ['FW12'], '12'),
    ('PPI-101-67238-FW4-3in', 'PPI', '101', '67238', ['FW4'], '3'),
    ('PPI-101-67249-W19&W26-6in', 'PPI', '101', '67249', ['W19', 'W26'], '6'),
    ('PPI-101-67253-FW4-6in', 'PPI', '101', '67253', ['FW4'], '6'),
    ('PPI-101-67262-FW3-3in', 'PPI', '101', '67262', ['FW3'], '3'),
    ('PPI-101-67274-FW2R1-8in', 'PPI', '101', '67274', ['FW2R1'], '8'),
    ('PPI-101-67276-FW21-10in', 'PPI', '101', '67276', ['FW21'], '10'),
    ('PPI-23-21092-W3&4-24in', 'PPI', '23', '21092', ['W3', 'W4'], '24'),
    ('PPI-27-66879-W2-8in', 'PPI', '27', '66879', ['W2'], '8'),
    ('PPI-30-47791-FW7,FW10-8in', 'PPI', '30', '47791', ['FW7', 'FW10'], '8'),
    ('PPI-31-37575-FW3&8', 'PPI', '31', '37575', ['FW3', 'FW8'], ''),
    ('PPI-31-37575-FW5&6', 'PPI', '31', '37575', ['FW5', 'FW6'], ''),
    ('PPI-31-37575-W28&29', 'PPI', '31', '37575', ['W28', 'W29'], ''),
    ('PPI-32-27119-FW2-4in', 'PPI', '32', '27119', ['FW2'], '4'),
    ('PPI-32-27119-FW6-4in', 'PPI', '32', '27119', ['FW6'], '4'),
    ('PPI-35-17906-FW6-6in', 'PPI', '35', '17906', ['FW6'], '6'),
    ('PPI-35-51251-FW4-2in', 'PPI', '35', '51251', ['FW4'], '2'),
    ('PPI-38-24390-FW1,2,3-2in', 'PPI', '38', '24390', ['FW1', 'FW2', 'FW3'], '2'),
    ('PPI-47-67223-FW7-2in', 'PPI', '47', '67223', ['FW7'], '2'),
    ('PPI-86-66990-FW12-2in', 'PPI', '86', '66990', ['FW12'], '2'),
    ('PPI-86-66990-FW6-2in', 'PPI', '86', '66990', ['FW6'], '2'),
    ('PPI-94-66773-W51-12in', 'PPI', '94', '66773', ['W51'], '12'),
    ('PPI-94-67013-FW44-24in', 'PPI', '94', '67013', ['FW44'], '24'),
    ('PPI-94-67013-W41-24in', 'PPI', '94', '67013', ['W41'], '24'),
]
NOT_JOBS = ['Beamtool snips', 'Weld Report Versions', 'Weld Reports from Kyle', 'test']


class FolderNameTests(TestCase):
    def test_every_real_job_folder_name(self):
        for name, client, unit, line, welds, nps in REAL_FOLDERS:
            with self.subTest(name):
                info = parse_folder_name(name)
                self.assertEqual((info['client_code'], info['unit'], info['line'], info['welds'], info['nps']),
                                 (client, unit, line, welds, nps))
                self.assertTrue(info['recognised'])

    def test_other_folders_are_not_jobs(self):
        for name in NOT_JOBS:
            with self.subTest(name):
                self.assertFalse(parse_folder_name(name)['recognised'])

    def test_invalid_names(self):
        self.assertTrue(invalid_name(''))
        self.assertTrue(invalid_name('PPI-32/27119'))
        self.assertEqual(invalid_name('PPI-32-27119-FW6&7-4in'), '')


class FolderListingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, files=()):
        folder = self.root / name
        folder.mkdir()
        for f in files:
            (folder / f).write_bytes(b'x')
        return folder

    def test_lists_job_folders_first_with_what_their_name_and_files_say(self):
        self.make('Weld Report Versions', ['Template.xlsx'])
        old = self.make('PPI-32-27119-FW2-4in', ['32-27119 fw2 off1.nde', 'PPI-32-27119-FW2-4in.xlsx'])
        os.utime(old, (1_700_000_000, 1_700_000_000))
        self.make('PPI-32-27119-FW6-4in', ['a.nde', 'b.NDE', 'ind 1.png'])
        folders = job_folders(self.root)
        self.assertEqual([f['name'] for f in folders],
                         ['PPI-32-27119-FW6-4in', 'PPI-32-27119-FW2-4in', 'Weld Report Versions'])
        self.assertEqual((folders[0]['nde'], folders[0]['reports'], folders[0]['info']['nps']), (2, [], '4'))
        self.assertEqual(folders[1]['reports'], ['PPI-32-27119-FW2-4in.xlsx'])
        self.assertFalse(folders[2]['job'])
        self.assertEqual([f.name for f in nde_files(self.root / 'PPI-32-27119-FW6-4in')], ['a.nde', 'b.NDE'])

    def test_only_folders_inside_the_root_resolve(self):
        self.make('PPI-32-27119-FW6-4in')
        self.assertEqual(resolve_job_folder('PPI-32-27119-FW6-4in', self.root),
                         (self.root / 'PPI-32-27119-FW6-4in').resolve())
        for name in ('', '..', '../..', 'missing', str(Path(self.tmp.name).parent)):
            self.assertIsNone(resolve_job_folder(name, self.root), name)
        self.assertIsNone(resolve_job_folder('PPI-32-27119-FW6-4in', None))


class WorkingFolderTests(TestCase):
    def setUp(self):
        WorkingFolder.objects.all().delete()   # the migration's (this PC's 001 Welds)
        self.tmp = tempfile.TemporaryDirectory()
        self.a, self.b = Path(self.tmp.name) / 'Welds A', Path(self.tmp.name) / 'Welds B'
        self.a.mkdir()
        self.b.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_default_per_report_type_and_the_first_is_it(self):
        first, _ = add_working_folder(str(self.a), 'paut_weld')
        second, _ = add_working_folder(f' "{self.b}" ', 'paut_weld')
        other, _ = add_working_folder(str(self.a), 'paut_long')
        self.assertEqual([f.is_default for f in (first, second, other)], [True, False, True])
        self.assertEqual(working_folder('paut_weld'), first)
        self.assertEqual(working_folder('paut_weld', second.pk), second)
        self.assertEqual(working_folder('paut_weld', other.pk), first)   # another type's isn't picked
        add_working_folder(str(self.b), 'paut_weld', is_default=True)   # the same path again: made the default
        self.assertEqual(WorkingFolder.objects.filter(report_type='paut_weld').count(), 2)
        self.assertEqual(working_folder('paut_weld'), second)
        self.assertIsNone(working_folder('paut_corrosion'))
        self.assertEqual(add_working_folder(str(self.a / 'nope'), 'paut_weld')[1], f'No folder at {self.a / "nope"}.')

    def test_preferences_tab_adds_edits_and_removes(self):
        resp = self.client.post(reverse('new-working-folder'), {'path': str(self.a), 'report_type': 'paut_weld'})
        self.assertRedirects(resp, reverse('working-folder-list'))
        folder = WorkingFolder.objects.get()
        self.assertTrue(folder.is_default)
        page = self.client.get(reverse('working-folder-list'))
        self.assertContains(page, 'Welds A')
        edit = self.client.get(reverse('edit-working-folder', args=[folder.pk]))
        self.assertContains(edit, 'data-browse-for="id_path"')
        bad = self.client.post(reverse('edit-working-folder', args=[folder.pk]), {'path': str(self.a / 'x'), 'report_type': 'paut_weld'})
        self.assertContains(bad, 'No folder at')
        self.client.post(reverse('working-folder-list'), {'delete': '1', 'selected': [folder.pk]})
        self.assertFalse(WorkingFolder.objects.exists())
        self.assertTrue(self.a.is_dir())   # only forgotten, never deleted on disk


class FolderDialogTests(TestCase):
    def test_pick_folder_runs_the_dialog_in_its_own_process(self):
        done = mock.Mock(returncode=0, stdout='C:/Users/me/Desktop/Reports/001 Welds'.encode(), stderr=b'')
        with mock.patch('reports.services.job_folder.subprocess.run', return_value=done) as run:
            self.assertEqual(pick_folder(), os.path.normpath('C:/Users/me/Desktop/Reports/001 Welds'))
        self.assertIn('askdirectory', run.call_args.args[0][2])
        cancelled = mock.Mock(returncode=0, stdout=b'', stderr=b'')
        with mock.patch('reports.services.job_folder.subprocess.run', return_value=cancelled):
            self.assertEqual(pick_folder(), '')

    def test_browse_endpoint_is_for_this_computer_only(self):
        with mock.patch('reports.views.working_folders.pick_folder', return_value=r'C:\Jobs') as pick:
            self.assertEqual(self.client.post(reverse('browse-folder'), {'initial': ''}).json(), {'path': r'C:\Jobs'})
            other = self.client.post(reverse('browse-folder'), REMOTE_ADDR='10.0.0.7').json()
        self.assertIn('only works on the computer running the app', other['error'])
        self.assertEqual(pick.call_count, 1)
        with mock.patch('reports.views.working_folders.pick_folder', side_effect=OSError('no display')):
            self.assertIn('no display', self.client.post(reverse('browse-folder')).json()['error'])
        self.assertEqual(self.client.get(reverse('browse-folder')).status_code, 405)


class ClientCodeLibraryTests(TestCase):
    def test_fhr_is_seeded_and_codes_are_kept_upper_case(self):
        self.assertEqual(ClientCode.objects.get(code='FHR').client, 'Flint Hills Resources')
        self.client.post(reverse('new-client-code'), {'code': 'ppi ', 'client': 'Pine Bend', 'location': ''})
        self.assertTrue(ClientCode.objects.filter(code='PPI').exists())
        page = self.client.get(reverse('client-code-list'))
        self.assertContains(page, 'Flint Hills Resources')
        self.assertContains(page, 'Client codes')
