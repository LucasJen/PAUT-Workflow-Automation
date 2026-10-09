"""
Which .nde files the Analysis page may open. Files are read where they are (never copied), so a
path from the browser is only accepted when it's a .nde file inside one of the working folders
(Preferences › Working folders) or settings.ANALYSIS_EXTRA_ROOTS.
"""
import os

from django.conf import settings


class PathNotAllowed(Exception):
    pass


def allowed_roots():
    """The folders .nde files may be opened from (real paths, no duplicates or nested repeats)."""
    from reports.models import WorkingFolder
    roots = [p for p in WorkingFolder.objects.values_list('path', flat=True) if p]
    roots += list(getattr(settings, 'ANALYSIS_EXTRA_ROOTS', []))
    real = sorted({os.path.normcase(os.path.realpath(r)) for r in roots if os.path.isdir(r)}, key=len)
    kept = []
    for root in real:
        if not any(_inside(root, outer) for outer in kept):
            kept.append(root)
    return kept


def _inside(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:   # different drives
        return False


def checked_path(path):
    """The real path of an allowed .nde file; PathNotAllowed otherwise."""
    if not path:
        raise PathNotAllowed('No file given.')
    real = os.path.normcase(os.path.realpath(path))
    if not real.endswith('.nde'):
        raise PathNotAllowed('Only .nde files can be opened.')
    if not any(_inside(real, root) for root in allowed_roots()):
        raise PathNotAllowed('That file is outside the working folders (Preferences › Working folders).')
    if not os.path.isfile(real):
        raise PathNotAllowed('That file no longer exists.')
    return real
