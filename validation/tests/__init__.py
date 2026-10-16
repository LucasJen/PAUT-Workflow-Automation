"""
The validation service's own tests. Runs made here keep their pictures in a temporary folder, never
with the real runs (the test database numbers its runs from 1 too).
"""
import atexit
import shutil
import tempfile

from django.conf import settings

_RUNS = tempfile.mkdtemp(prefix='validation-test-runs-')
settings.VALIDATION_RUNS_DIR = _RUNS
atexit.register(shutil.rmtree, _RUNS, True)
