"""
A new project from .nde files opened on the Analysis page: a job folder made in the report type's
working folder (Preferences › Working folders), the files copied into it - in the background, as
they can be a gigabyte each - and then Guided Creation "From scan files" on that folder.
"""
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

from django.urls import reverse
from django.utils.http import urlencode

from reports.report_types import REPORT_TYPES
from reports.services.job_folder import invalid_name, working_folder

CHUNK = 8 * 1024 * 1024
_jobs = {}              # id -> {'state', 'copied', 'total', 'file', 'error', 'next_url'}
_lock = threading.Lock()


class ProjectError(Exception):
    """Something the user should be told."""


def suggested_name(paths):
    """'PPI 31-37575 w5 n off1.nde', 'PPI 31-37575 w6 s off1.nde' -> 'PPI-31-37575-W5&W6'."""
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    if not stems:
        return ''
    prefix = os.path.commonprefix(stems) if len(stems) > 1 else stems[0]
    welds = []
    for stem in stems:
        found = re.search(r'\b(f?w\d+[a-z]?\d*)\b', stem, flags=re.I)
        if found and found.group(1).upper() not in welds:
            welds.append(found.group(1).upper())
    prefix = re.sub(r'[\s_-]*(?:f?w\d*)?[\s_-]*$', '', prefix, flags=re.I).strip() if welds else prefix.strip(' _-')
    parts = [re.sub(r'\s+', '-', prefix)] if prefix else []
    if welds:
        parts.append('&'.join(welds))
    return re.sub(r'[<>:"/\\|?*]', '', '-'.join(parts))[:120]


def suggested_type(paths):
    """The report type the files look like: angle-beam groups a weld report, 0 deg rasters a Short Form."""
    from analysis.services.nde_data import NdeDataError, open_file
    layouts = set()
    for path in paths[:5]:
        try:
            layouts |= {g.layout for g in open_file(path).groups}
        except (NdeDataError, OSError):
            continue
    if 'beams' in layouts:
        return 'paut_weld'
    if 'raster' in layouts:
        return 'paut_corrosion'
    return ''


def options(paths):
    """What the New project form offers: the guided report types with their working folders, a name."""
    types = []
    for t in REPORT_TYPES.values():
        if not t.guided:
            continue
        root = working_folder(t.key)
        types.append({'key': t.key, 'label': t.label, 'root': root.path if root else '',
                      'root_ok': bool(root and os.path.isdir(root.path))})
    return {'types': types, 'name': suggested_name(paths), 'suggested_type': suggested_type(paths)}


def start(paths, report_type, name):
    """Makes the job folder and starts copying the files into it; returns the job's id."""
    rtype = REPORT_TYPES.get(report_type)
    if rtype is None or not rtype.guided:
        raise ProjectError('Pick a report type Guided Creation can build.')
    root = working_folder(rtype.key)
    if root is None:
        raise ProjectError(f'Set a working folder for {rtype.label} reports in Preferences › Working folders first.')
    if not os.path.isdir(root.path):
        raise ProjectError(f"The working folder {root.path} isn't there; change it in Preferences › Working folders.")
    name = (name or '').strip()
    problem = invalid_name(name)
    if problem:
        raise ProjectError(problem)
    if not paths:
        raise ProjectError('Pick the .nde files for the project.')
    folder = Path(root.path) / name
    folder.mkdir(exist_ok=True)
    # Files already there (same name and size) aren't copied again
    todo = [p for p in paths if not ((folder / os.path.basename(p)).is_file()
                                     and (folder / os.path.basename(p)).stat().st_size == os.path.getsize(p))]
    job_id = uuid.uuid4().hex
    next_url = f"{reverse('start-from-files')}?{urlencode({'type': rtype.key, 'folder': name})}"
    job = {'state': 'running', 'copied': 0, 'total': sum(os.path.getsize(p) for p in todo), 'file': '',
           'error': '', 'next_url': next_url, 'folder': str(folder)}
    with _lock:
        _jobs[job_id] = job

    def run():
        try:
            for source in todo:
                target = folder / os.path.basename(source)
                job['file'] = target.name
                partial = target.with_name(target.name + '.part')
                with open(source, 'rb') as src, open(partial, 'wb') as out:
                    while True:
                        block = src.read(CHUNK)
                        if not block:
                            break
                        out.write(block)
                        job['copied'] += len(block)
                shutil.copystat(source, partial)
                os.replace(partial, target)
            job['state'] = 'done'
        except OSError as e:
            job['state'], job['error'] = 'error', f"Couldn't copy {job['file']}: {e.strerror or e}"

    threading.Thread(target=run, daemon=True, name=f'analysis-project-{job_id[:8]}').start()
    return job_id


def status(job_id):
    job = _jobs.get(job_id)
    if job is None:
        return None
    return {k: job[k] for k in ('state', 'copied', 'total', 'file', 'error', 'next_url', 'folder')}
