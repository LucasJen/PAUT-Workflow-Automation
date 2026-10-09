"""
Backups of the app's data: the database (db.sqlite3) and the uploaded files (media/).

Each backup is a dated copy of the database, backup_<YYYY-MM-DD_HHMMSS>.sqlite3, in BACKUP_DIR,
made with SQLite's backup API so it is consistent even while the app is writing. The newest
BACKUP_KEEP of these are kept; copies made by hand (any other name) are never touched.

Uploaded files are only ever added (a replaced picture gets a new name), so instead of a zip per
backup, media/ is mirrored into BACKUP_DIR/media: each backup copies the files that are new or
changed since the last one, and files deleted from the app stay in the mirror. Restoring a backup
is copying its .sqlite3 over db.sqlite3 and the mirror over media/ (with the app stopped).

A backup is made on the first request of each day (DailyBackupMiddleware) and from Preferences ›
Backups ("Back up now").
"""
import logging
import os
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

BACKUP_KEEP = 14
NAME = re.compile(r'^backup_(\d{4}-\d{2}-\d{2})_(\d{6})\.sqlite3$')

_lock = threading.Lock()


class BackupError(Exception):
    """A backup couldn't be made."""


def backup_dir():
    return Path(getattr(settings, 'BACKUP_DIR', None) or Path(settings.BASE_DIR) / 'outputs' / 'db_backups')


def backups():
    """The app's backups, newest first: [{'name', 'path', 'when' (datetime), 'size'}]."""
    folder = backup_dir()
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        match = NAME.match(path.name)
        if match:
            when = datetime.strptime(f'{match[1]}_{match[2]}', '%Y-%m-%d_%H%M%S')
            found.append({'name': path.name, 'path': path, 'when': when, 'size': path.stat().st_size})
    return sorted(found, key=lambda b: b['when'], reverse=True)


def _copy_database(target):
    """The live database into `target` (SQLite's online backup, through Django's connection: a consistent copy)."""
    connection.ensure_connection()
    dst = sqlite3.connect(str(target))
    try:
        connection.connection.backup(dst)
    finally:
        dst.close()


def _mirror_media(target):
    """Copies the files in media/ that are missing from `target` or differ in size / time. Returns how many."""
    source = Path(settings.MEDIA_ROOT)
    copied = 0
    if not source.is_dir():
        return copied
    for root, _, files in os.walk(source):
        for name in files:
            src = Path(root) / name
            dst = target / src.relative_to(source)
            stat = src.stat()
            if dst.exists():
                existing = dst.stat()
                if existing.st_size == stat.st_size and int(existing.st_mtime) == int(stat.st_mtime):
                    continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    return copied


def prune(keep=BACKUP_KEEP):
    """Deletes the app's backups beyond the newest `keep`. Returns the names deleted."""
    deleted = []
    for old in backups()[keep:]:
        try:
            old['path'].unlink()
            deleted.append(old['name'])
        except OSError:
            logger.warning('Could not delete old backup %s', old['path'])
    return deleted


def make_backup():
    """A new backup now. Returns {'name', 'size', 'media_copied'}; raises BackupError."""
    if connection.vendor != 'sqlite':
        raise BackupError('Backups are only made of the SQLite database.')
    with _lock:
        folder = backup_dir()
        name = f'backup_{datetime.now():%Y-%m-%d_%H%M%S}.sqlite3'
        target = folder / name
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if target.exists():   # two in the same second
                return {'name': name, 'size': target.stat().st_size, 'media_copied': 0}
            _copy_database(target)
            media_copied = _mirror_media(folder / 'media')
        except (OSError, sqlite3.Error) as e:
            logger.exception('Backup failed')
            target.unlink(missing_ok=True)
            raise BackupError(f'The backup could not be made: {e}') from e
        prune()
        logger.info('Backup %s made (%s media files copied)', name, media_copied)
        return {'name': name, 'size': target.stat().st_size, 'media_copied': media_copied}


def backed_up_today():
    today = datetime.now().date()
    return any(b['when'].date() == today for b in backups())


def daily_backup():
    """Makes today's backup if there isn't one yet; never raises (it runs behind a request)."""
    try:
        if not backed_up_today():
            make_backup()
    except Exception:
        logger.exception('Daily backup failed')
    finally:
        connection.close()   # this thread's own connection


class DailyBackupMiddleware:
    """
    On the first request of each day, makes that day's backup on a background thread (so the
    page isn't held up). Off when settings.AUTO_BACKUP is False (e.g. while the tests run).
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.checked = None   # the date today's backup was last seen to / started

    def __call__(self, request):
        today = datetime.now().date()
        if getattr(settings, 'AUTO_BACKUP', False) and self.checked != today:
            self.checked = today
            threading.Thread(target=daily_backup, name='daily-backup', daemon=True).start()
        return self.get_response(request)
