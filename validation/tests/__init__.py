"""
The validation service's own tests. Runs made here keep their pictures in a temporary folder, never
with the real runs (the test database numbers its runs from 1 too), and build C-scans in another.
"""
import atexit
import shutil
import tempfile

from django.conf import settings

_RUNS = tempfile.mkdtemp(prefix='validation-test-runs-')
settings.VALIDATION_RUNS_DIR = _RUNS
atexit.register(shutil.rmtree, _RUNS, True)
# and the C-scans the checks build for their synthetic files, never in the page's cache
_CACHE = tempfile.mkdtemp(prefix='validation-test-cache-')
settings.ANALYSIS_CACHE_DIR = _CACHE
atexit.register(shutil.rmtree, _CACHE, True)
