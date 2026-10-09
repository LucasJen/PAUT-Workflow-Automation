import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from django.test import RequestFactory, TransactionTestCase, override_settings
from django.urls import reverse

from reports.models import Report
from reports.services import backup


class BackupTests(TransactionTestCase):
    # Real commits: SQLite's backup waits on a write transaction left open (TestCase's)
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / 'media' / 'report_images').mkdir(parents=True)
        (self.tmp / 'media' / 'report_images' / 'a.png').write_bytes(b'png')
        override = override_settings(BACKUP_DIR=self.tmp / 'backups', MEDIA_ROOT=self.tmp / 'media')
        override.enable()
        self.addCleanup(override.disable)

    def test_backup_copies_the_database_and_mirrors_media(self):
        Report.objects.create(document_filename='Backed up')
        made = backup.make_backup()
        self.assertEqual(made['media_copied'], 1)
        import sqlite3
        copy = sqlite3.connect(str(self.tmp / 'backups' / made['name']))
        self.assertEqual(copy.execute('select document_filename from reports_report').fetchall(), [('Backed up',)])
        copy.close()
        self.assertEqual((self.tmp / 'backups' / 'media' / 'report_images' / 'a.png').read_bytes(), b'png')

    def test_only_new_media_is_copied_again(self):
        with mock.patch.object(backup, 'datetime', wraps=datetime) as dt:
            dt.now.return_value = datetime(2026, 10, 1, 8, 0, 0)
            backup.make_backup()
            (self.tmp / 'media' / 'report_images' / 'b.png').write_bytes(b'png2')
            dt.now.return_value = datetime(2026, 10, 2, 8, 0, 0)
            self.assertEqual(backup.make_backup()['media_copied'], 1)

    def test_keeps_the_newest_and_leaves_hand_made_copies(self):
        folder = self.tmp / 'backups'
        folder.mkdir()
        for day in range(1, 18):
            (folder / f'backup_2026-09-{day:02d}_080000.sqlite3').write_bytes(b'')
        (folder / 'db_before_merge.sqlite3').write_bytes(b'')
        backup.prune()
        left = sorted(p.name for p in folder.iterdir())
        self.assertEqual(len([n for n in left if n.startswith('backup_')]), backup.BACKUP_KEEP)
        self.assertIn('backup_2026-09-17_080000.sqlite3', left)
        self.assertNotIn('backup_2026-09-03_080000.sqlite3', left)
        self.assertIn('db_before_merge.sqlite3', left)

    def test_daily_backup_only_once_a_day(self):
        with mock.patch.object(backup, 'make_backup') as make:
            backup.daily_backup()
            self.assertEqual(make.call_count, 1)
        backup.make_backup()
        with mock.patch.object(backup, 'make_backup') as make:
            backup.daily_backup()
            make.assert_not_called()

    def test_middleware_starts_one_check_per_day(self):
        middleware = backup.DailyBackupMiddleware(lambda request: 'ok')
        request = RequestFactory().get('/')
        with override_settings(AUTO_BACKUP=True), mock.patch.object(backup.threading, 'Thread') as thread:
            middleware(request)
            middleware(request)
        self.assertEqual(thread.call_count, 1)

    def test_back_up_now_page(self):
        resp = self.client.post(reverse('backup-list'), {'backup': '1'}, follow=True)
        self.assertContains(resp, 'Backed up to backup_')
        self.assertEqual(len(backup.backups()), 1)


class UnusedFilesTests(TransactionTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        override = override_settings(BACKUP_DIR=self.tmp / 'backups', MEDIA_ROOT=self.tmp / 'media')
        override.enable()
        self.addCleanup(override.disable)
        images = self.tmp / 'media' / 'report_images'
        images.mkdir(parents=True)
        old = datetime(2026, 1, 1).timestamp()
        for name in ('used.png', 'shared.png', 'orphan.png', 'new.png'):
            (images / name).write_bytes(b'x' * 10)
            if name != 'new.png':
                os.utime(images / name, (old, old))

    def test_only_files_nothing_uses_are_deleted_after_a_backup(self):
        from reports.models import ReportImage
        from reports.services.media_cleanup import unused_files
        report, copy = Report.objects.create(), Report.objects.create()
        ReportImage.objects.create(report=report, image='report_images/used.png')
        # A duplicate shares its original's file
        ReportImage.objects.create(report=copy, image='report_images/shared.png')
        # new.png is too recent to offer (a save may still be using it)
        self.assertEqual([f['name'] for f in unused_files()], ['report_images/orphan.png'])

        resp = self.client.post(reverse('backup-list'), {'delete_unused': '1'}, follow=True)
        self.assertContains(resp, 'Deleted 1 unused file')
        left = sorted(p.name for p in (self.tmp / 'media' / 'report_images').iterdir())
        self.assertEqual(left, ['new.png', 'shared.png', 'used.png'])
        self.assertTrue((self.tmp / 'backups' / 'media' / 'report_images' / 'orphan.png').exists())
        self.assertEqual(len(backup.backups()), 1)
