"""
Job folders: the working directory a weld report is made from and saved into, e.g.
Desktop\\Reports\\001 Welds\\PPI-32-27119-FW6-4in, holding the job's .nde files and the report
({folder name}.xlsx / .pdf). The folder name follows {CLIENT}-{UNIT}-{LINE}-{WELDS}-{SIZE}in;
parse_folder_name() reads it back (client code, line, welds, NPS) for Guided Creation.
"""
import os
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings

ROOT_SETTING = 'jobs_root'

CLIENT = re.compile(r'^[A-Za-z]{2,6}$')
NUMBER = re.compile(r'^\d+$')
SIZE = re.compile(r'^(\d+(?:\.\d+)?)\s*in(?:ch(?:es)?)?$', re.I)
# A weld: W5, FW12, BW3, WP10, FW2R1 (repair 1); later welds of a list may be bare numbers (W1&2)
WELD = re.compile(r'^(F?W|BW|WP)-?(\d+[A-Z]*\d*)$', re.I)
BARE_WELD = re.compile(r'^\d+[A-Z]*\d*$', re.I)
# Characters Windows doesn't allow in a folder name
INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ── Folder names ─────────────────────────────────────────────────────────────

def _welds(text):
    """'W1&2' -> ['W1', 'W2']; 'FW7,FW10' -> ['FW7', 'FW10']; 'FW1.2' -> ['FW1', 'FW2']; 'WP-10' -> ['WP10']."""
    welds, prefix = [], ''
    for part in (p.strip() for p in re.split(r'[&,.]', text)):
        match = WELD.match(part)
        if match:
            prefix = match.group(1).upper()
            welds.append(f'{prefix}{match.group(2).upper()}')
        elif prefix and BARE_WELD.match(part):
            welds.append(f'{prefix}{part.upper()}')
        elif part:
            return []   # not a weld list
    return welds


def parse_folder_name(name):
    """
    What a job folder's name says: {'client_code', 'unit', 'line', 'welds', 'nps', 'recognised'}.
    'PPI-32-27119-FW6-4in' -> PPI, 32, 27119, ['FW6'], '4'; 'FHR-6302-W11-2in' has no unit;
    the size can come before the welds ('FHR-23-56351-2in-W5&30&34') or be missing ('' then).
    """
    tokens = [t for t in name.strip().split('-') if t.strip()]
    info = {'client_code': '', 'unit': '', 'line': '', 'welds': [], 'nps': '', 'recognised': False}
    if tokens and CLIENT.match(tokens[0]):
        info['client_code'] = tokens.pop(0).upper()
    numbers = []
    while tokens and NUMBER.match(tokens[0]) and len(numbers) < 2:
        numbers.append(tokens.pop(0))
    if len(numbers) == 2:
        info['unit'], info['line'] = numbers
    elif numbers:
        info['line'] = numbers[0]
    rest = []
    for token in tokens:
        size = SIZE.match(token.strip())
        if size and not info['nps']:
            info['nps'] = size.group(1)
        else:
            rest.append(token)
    info['welds'] = _welds('-'.join(rest)) if rest else []
    info['recognised'] = bool(info['client_code'] and info['line'] and (info['welds'] or info['nps']))
    return info


def invalid_name(name):
    """Why `name` can't be a folder name, or ''."""
    if not name.strip():
        return 'Type the new folder\'s name, e.g. PPI-32-27119-FW6-4in.'
    if INVALID.search(name) or name.strip().endswith('.'):
        return f'“{name}” has characters a folder name can\'t have.'
    return ''


# ── The jobs root (where job folders are listed and created) ─────────────────

def jobs_root():
    """The folder holding the job folders: the one set in the app, else settings.WELD_JOBS_DIR."""
    from ..models import AppSetting
    return Path(AppSetting.get(ROOT_SETTING) or settings.WELD_JOBS_DIR)


def set_jobs_root(path):
    """Remembers `path` as the jobs root; returns '' or why it can't be used."""
    from ..models import AppSetting
    path = (path or '').strip().strip('"')
    if not path:
        AppSetting.objects.filter(key=ROOT_SETTING).delete()   # back to the default
        return ''
    if not os.path.isdir(path):
        return f'No folder at {path}.'
    AppSetting.put(ROOT_SETTING, str(Path(path).resolve()))
    return ''


def resolve_job_folder(name, root=None):
    """The job folder `name` (a folder in the root, or a path inside it) as a Path, or None if it isn't one."""
    root = Path(root or jobs_root()).resolve()
    if not name:
        return None
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root) or not path.is_dir():
        return None
    return path


# ── Listing and reading job folders ──────────────────────────────────────────

def report_files(folder, name=None):
    """The report outputs named after the folder that are in it: ['…xlsx', '…pdf']."""
    name = name or Path(folder).name
    return [f'{name}{ext}' for ext in ('.xlsx', '.pdf', '.docx') if (Path(folder) / f'{name}{ext}').is_file()]


def job_folders(root=None):
    """
    The root's folders as [{name, path, info (parse), nde (count), reports, modified}]: job folders
    (a recognised name or .nde files in them) newest first, then the others.
    """
    root = Path(root or jobs_root())
    try:
        entries = [e for e in os.scandir(root) if e.is_dir() and not e.name.startswith('.')]
    except OSError:
        return []
    folders = []
    for entry in entries:
        try:
            nde = sum(1 for f in os.scandir(entry.path) if f.is_file() and f.name.lower().endswith('.nde'))
            modified = entry.stat().st_mtime
        except OSError:
            continue
        info = parse_folder_name(entry.name)
        folders.append({'name': entry.name, 'path': entry.path, 'info': info, 'nde': nde,
                        'reports': report_files(entry.path, entry.name),
                        'modified': datetime.fromtimestamp(modified), 'job': info['recognised'] or nde > 0})
    folders.sort(key=lambda f: (not f['job'], -f['modified'].timestamp()))
    return folders


class DiskNde:
    """An .nde in a job folder, read in place like an upload (read_nde opens it by path: metadata only)."""

    def __init__(self, path):
        self.path = str(path)
        self.name = os.path.basename(self.path)

    def temporary_file_path(self):
        return self.path

    def read(self):
        with open(self.path, 'rb') as f:
            return f.read()


def nde_files(folder):
    """The folder's .nde files (top level), by name."""
    folder = Path(folder)
    return [DiskNde(p) for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if p.is_file() and p.suffix.lower() == '.nde']


def save_uploads(folder, uploads):
    """Copies uploaded .nde files into the folder (an existing file of that name is kept); returns the names saved."""
    saved = []
    for uploaded in uploads:
        target = Path(folder) / os.path.basename(uploaded.name)
        if target.exists():
            continue
        with open(target, 'wb') as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        saved.append(target.name)
    return saved
