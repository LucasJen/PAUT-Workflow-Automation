"""
Unused files in media/: pictures and documents no record points to any more (left behind when a
report, setup or image is deleted; duplicated reports share their files, so they're only removed
here, once nothing uses them). Preferences › Backups lists them and deletes them on request, after
a backup: the backup's media mirror keeps a copy of each.
"""
import os
import time
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models

RECENT_SECONDS = 3600   # a file this new may belong to a save still in progress: never offered


def referenced_files():
    """Every file a FileField / ImageField of any model points to, as paths relative to media/ ('/' separated)."""
    names = set()
    for model in apps.get_models():
        fields = [f.name for f in model._meta.concrete_fields if isinstance(f, models.FileField)]
        for field in fields:
            for name in model.objects.exclude(**{field: ''}).values_list(field, flat=True):
                if name:
                    names.add(name.replace('\\', '/'))
    return names


def unused_files(now=None):
    """[{'name', 'path', 'size'}] of the files in media/ nothing points to, biggest first."""
    root = Path(settings.MEDIA_ROOT)
    if not root.is_dir():
        return []
    used = referenced_files()
    now = now or time.time()
    found = []
    for folder, _, files in os.walk(root):
        for file in files:
            path = Path(folder) / file
            name = path.relative_to(root).as_posix()
            stat = path.stat()
            if name in used or now - stat.st_mtime < RECENT_SECONDS:
                continue
            found.append({'name': name, 'path': path, 'size': stat.st_size})
    return sorted(found, key=lambda f: f['size'], reverse=True)


def delete_unused():
    """Deletes the unused files (the caller backs up first). Returns (count, bytes) deleted."""
    count = size = 0
    for file in unused_files():
        try:
            file['path'].unlink()
        except OSError:
            continue
        count, size = count + 1, size + file['size']
    return count, size
