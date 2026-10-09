"""
The last few outputs Word or Excel made, kept so Preview then Download (or .xlsx then PDF)
doesn't start Office again. Each is filed under a fingerprint of everything that goes into it
(the filled .docx's contents, or the Excel form's cell values, pictures and template), so a
changed report, picture, scan plan or template simply misses and is made afresh.
"""
import dataclasses
import hashlib
import io
import os
import threading
import zipfile
from collections import OrderedDict
from datetime import date, datetime
from decimal import Decimal

from django.db import models
from django.db.models.fields.files import FieldFile

MAX_ENTRIES = 12
_entries = OrderedDict()
_lock = threading.Lock()


def get(key):
    with _lock:
        value = _entries.get(key)
        if value is not None:
            _entries.move_to_end(key)
        return value


def put(key, value):
    with _lock:
        _entries[key] = value
        _entries.move_to_end(key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def clear():
    with _lock:
        _entries.clear()


def docx_fingerprint(content):
    """A filled .docx's fingerprint: its parts' contents (the zip's own timestamps change every save)."""
    h = hashlib.sha256(b'docx')
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for name in sorted(z.namelist()):
            h.update(name.encode())
            h.update(hashlib.sha256(z.read(name)).digest())
    return h.hexdigest()


def _file(h, path):
    """A file's contents (not its path: pictures are written to a new temporary folder each time)."""
    h.update(b'file')
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        h.update(b'missing')


def _update(h, value):
    """Feeds `value` into the hash: dataclasses, models, containers and scalars; a string naming a
    file also feeds the file's contents (pictures)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        h.update(type(value).__name__.encode())
        for item in dataclasses.fields(value):
            h.update(item.name.encode())
            _update(h, getattr(value, item.name))
    elif isinstance(value, models.Model):
        h.update(type(value).__name__.encode())
        for item in value._meta.concrete_fields:
            h.update(item.attname.encode())
            _update(h, item.value_from_object(value))
    elif isinstance(value, dict):
        h.update(b'{')
        for key in sorted(value, key=repr):
            _update(h, key)
            _update(h, value[key])
        h.update(b'}')
    elif isinstance(value, (list, tuple)):
        h.update(b'[')
        for item in value:
            _update(h, item)
        h.update(b']')
    elif isinstance(value, (bytes, bytearray)):
        h.update(b'bytes')
        h.update(hashlib.sha256(value).digest())
    elif isinstance(value, str):
        if len(value) < 400 and os.path.isabs(value) and os.path.isfile(value):
            _file(h, value)
        else:
            h.update(b'str')
            h.update(value.encode('utf-8', 'surrogatepass'))
    elif value is None or isinstance(value, (bool, int, float, Decimal, date, datetime)):
        h.update(repr(value).encode())
    elif isinstance(value, FieldFile):
        h.update(str(value.name).encode())
        if value.name:
            _file(h, value.path)
    else:
        h.update(repr(value).encode())


def fingerprint(*parts, files=()):
    """A fingerprint of `parts` (see _update) and the contents of `files`."""
    h = hashlib.sha256()
    for part in parts:
        _update(h, part)
    for path in files:
        _file(h, path)
    return h.hexdigest()
