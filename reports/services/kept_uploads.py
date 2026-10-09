"""
Pictures chosen in the report editor survive a save that fails (a highlighted field, or a newer
version saved from another tab): a browser can't refill a file box, so the files are kept in a
temporary folder and the page carries a 'kept_upload' field for each ('<field name>|<token>/<file>').
The next save posts them again as if chosen, unless a new file was picked for the same box.
"""
import mimetypes
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.datastructures import MultiValueDict

FIELD = 'kept_upload'
KEEP_FOR = 24 * 3600   # seconds; older kept files are cleared out
_REF = re.compile(r'^[0-9a-f]{32}/[^/\\]+$')


def kept_root():
    return Path(tempfile.gettempdir()) / 'paut_report_uploads'


def _clear_old(root):
    cutoff = time.time() - KEEP_FOR
    for folder in root.iterdir() if root.is_dir() else ():
        try:
            if folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def _safe_name(name):
    return re.sub(r'[^\w.\- ]', '_', Path(name).name)[:120] or 'picture'


def keep(files):
    """Stores every file of a failed save; returns [(field name, reference, file name)] for the page."""
    if not files:
        return []
    root = kept_root()
    root.mkdir(parents=True, exist_ok=True)
    _clear_old(root)
    token = uuid.uuid4().hex
    folder = root / token
    folder.mkdir()
    kept = []
    for field, uploads in files.lists():
        for i, upload in enumerate(uploads):
            name = f'{i}_{_safe_name(upload.name)}'
            with open(folder / name, 'wb') as out:
                for chunk in upload.chunks():
                    out.write(chunk)
            kept.append((field, f'{token}/{name}', upload.name))
    return kept


def _read(reference):
    if not _REF.match(reference):
        return None
    path = kept_root() / reference
    if not path.is_file():
        return None
    name = path.name.split('_', 1)[-1]
    return SimpleUploadedFile(name, path.read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream')


def with_kept(post, files):
    """The files of a save: those chosen now, plus the kept ones of boxes left empty this time."""
    merged = MultiValueDict({field: list(uploads) for field, uploads in files.lists()})
    for value in post.getlist(FIELD):
        field, _, reference = value.partition('|')
        if not field or field in files:   # a new choice replaces what was kept for that box
            continue
        upload = _read(reference)
        if upload is not None:
            merged.appendlist(field, upload)
    return merged


def discard(post):
    """After a successful save: the kept files are in the report now."""
    for value in post.getlist(FIELD):
        reference = value.partition('|')[2]
        if _REF.match(reference):
            shutil.rmtree(kept_root() / reference.split('/')[0], ignore_errors=True)
