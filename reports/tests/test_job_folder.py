"""Job folders: reading the job folder names, listing / resolving them, and the jobs root."""
import os
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from reports.models import AppSetting, ClientCode
from reports.services.job_folder import (
    folder_name, invalid_name, job_folders, jobs_root, nde_files, parse_folder_name, resolve_job_folder,
    set_jobs_root, split_welds,
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

    def test_a_built_name_reads_back_the_same(self):
        for name, *_ in REAL_FOLDERS:
            info = parse_folder_name(name)
            built = folder_name(info['client_code'], info['unit'], info['line'], info['welds'], info['nps'])
            again = parse_folder_name(built)
            self.assertEqual({k: again[k] for k in ('client_code', 'unit', 'line', 'welds', 'nps')},
                             {k: info[k] for k in ('client_code', 'unit', 'line', 'welds', 'nps')}, built)

    def test_folder_name_for_a_new_job(self):
        self.assertEqual(folder_name('ppi', '32', '27119', split_welds('FW6, FW7'), '4'), 'PPI-32-27119-FW6&7-4in')
        self.assertEqual(folder_name('FHR', '', '6302', ['W11'], '2in'), 'FHR-6302-W11-2in')
        self.assertEqual(folder_name('FHR', '75', '62816', split_welds('W3&5'), ''), 'FHR-75-62816-W3&5')
        self.assertEqual(split_welds('W1 W2 W3'), ['W1', 'W2', 'W3'])

    def test_invalid_names(self):
        self.assertTrue(invalid_name(''))
        self.assertTrue(invalid_name('PPI-32/27119'))
        self.assertEqual(invalid_name('PPI-32-27119-FW6&7-4in'), '')


class FolderListingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.override = override_settings(WELD_JOBS_DIR=self.root)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
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
        folders = job_folders()
        self.assertEqual([f['name'] for f in folders],
                         ['PPI-32-27119-FW6-4in', 'PPI-32-27119-FW2-4in', 'Weld Report Versions'])
        self.assertEqual((folders[0]['nde'], folders[0]['reports'], folders[0]['info']['nps']), (2, [], '4'))
        self.assertEqual(folders[1]['reports'], ['PPI-32-27119-FW2-4in.xlsx'])
        self.assertFalse(folders[2]['job'])
        self.assertEqual([f.name for f in nde_files(self.root / 'PPI-32-27119-FW6-4in')], ['a.nde', 'b.NDE'])

    def test_only_folders_inside_the_root_resolve(self):
        self.make('PPI-32-27119-FW6-4in')
        self.assertEqual(resolve_job_folder('PPI-32-27119-FW6-4in'), (self.root / 'PPI-32-27119-FW6-4in').resolve())
        for name in ('', '..', '../..', 'missing', str(Path(self.tmp.name).parent)):
            self.assertIsNone(resolve_job_folder(name), name)

    def test_the_jobs_root_can_be_changed_and_reset(self):
        self.assertEqual(jobs_root(), self.root)
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual(set_jobs_root(other), '')
            self.assertEqual(jobs_root(), Path(other).resolve())
            self.assertIn('No folder', set_jobs_root(os.path.join(other, 'nope')))
        self.assertEqual(set_jobs_root(''), '')
        self.assertFalse(AppSetting.objects.exists())
        self.assertEqual(jobs_root(), self.root)


class ClientCodeLibraryTests(TestCase):
    def test_fhr_is_seeded_and_codes_are_kept_upper_case(self):
        self.assertEqual(ClientCode.objects.get(code='FHR').client, 'Flint Hills Resources')
        self.client.post(reverse('new-client-code'), {'code': 'ppi ', 'client': 'Pine Bend', 'location': ''})
        self.assertTrue(ClientCode.objects.filter(code='PPI').exists())
        page = self.client.get(reverse('client-code-list'))
        self.assertContains(page, 'Flint Hills Resources')
        self.assertContains(page, 'Client codes')
