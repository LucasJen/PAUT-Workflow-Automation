"""
Browse this PC: the drives, a few usual places and, inside a folder, its sub-folders and .nde
files - nothing else is listed - so a file outside the working folders can be picked and opened
where it is (the page then records it as an OpenedFile).
"""
import os
import string
from pathlib import Path


def places():
    """The drives there are and the user's usual folders: [{name, path, kind}]."""
    out = []
    home = Path.home()
    for name in ('Desktop', 'Documents', 'Downloads'):
        folder = home / name
        if folder.is_dir():
            out.append({'name': name, 'path': str(folder), 'kind': 'place'})
    if os.name == 'nt':
        for letter in string.ascii_uppercase:
            drive = f'{letter}:' + os.sep
            if os.path.exists(drive):
                out.append({'name': f'{letter}:', 'path': drive, 'kind': 'drive'})
    else:
        out.append({'name': '/', 'path': '/', 'kind': 'drive'})
    return out


def listing(path):
    """
    {path, parent, folders: [{name, path}], files: [{name, path, size, modified}]} for a folder, or
    raises ValueError. Hidden and unreadable entries are skipped.
    """
    folder = Path(path)
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError("That folder isn't there.")
    folders, files = [], []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        raise ValueError("That folder can't be read.")
    for entry in entries:
        if entry.name.startswith(('.', '$')):
            continue
        try:
            if entry.is_dir():
                folders.append({'name': entry.name, 'path': entry.path})
            elif entry.is_file() and entry.name.lower().endswith('.nde'):
                stat = entry.stat()
                files.append({'name': entry.name, 'path': entry.path, 'size': stat.st_size, 'modified': stat.st_mtime})
        except OSError:
            continue
    folders.sort(key=lambda f: f['name'].lower())
    files.sort(key=lambda f: f['name'].lower())
    parent = str(folder.parent) if folder.parent != folder else ''
    return {'path': str(folder), 'parent': parent, 'folders': folders, 'files': files}
