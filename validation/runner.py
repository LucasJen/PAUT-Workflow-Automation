"""
Runs a validation: fingerprints the kit first (a changed or missing file is a failure and isn't used),
then each chosen layer in turn, saving the run's results as it goes so the page can show them live.
Runs in a background thread from the page (start), or in the foreground from the validate command.
"""
import os
import platform
import subprocess
import threading
import time
import traceback

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .checks import BY_ID, LAYERS
from .kit import Kit, KitError
from .models import ValidationRun

_cancel = set()
_lock = threading.Lock()


def app_version():
    """The git commit the app is running at, '+ modified' with uncommitted changes; 'unknown' without git."""
    try:
        def git(*args):
            return subprocess.run(['git', *args], cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=10).stdout.strip()
        commit = git('rev-parse', '--short=10', 'HEAD')
        if not commit:
            return 'unknown'
        return commit + (' + modified' if git('status', '--porcelain', '--untracked-files=no') else '')
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


class Context:
    """What a layer gets: the kit, its verified files, options, and ways to report."""

    def __init__(self, run, kit, files, layer, save):
        self.run, self.kit, self.files, self.options = run, kit, files, run.options
        self.layer, self._save = layer, save

    def emit(self, check):
        self.layer['checks'].append(check)
        if check['kind'] == 'check':
            self.layer['passed' if check['passed'] else 'failed'] += 1
        self._save()

    def progress(self, message, fraction):
        self.layer['message'], self.layer['progress'] = message, round(min(1.0, max(0.0, fraction)), 3)
        self._save(throttle=True)

    def message(self, text):
        self.layer['message'] = text
        self._save()

    def cancelled(self):
        return self.run.pk in _cancel


def create(layers, kit_path, options=None):
    """A new run (not started) for these layer ids."""
    layers = [lid for lid in (layers or [layer.id for layer in LAYERS]) if lid in BY_ID]
    results = {'kit': {'status': 'pending', 'files': []},
               'layers': [{'id': lid, 'title': BY_ID[lid].title, 'question': BY_ID[lid].question,
                           'against': BY_ID[lid].against, 'status': 'pending' if BY_ID[lid].run else 'not built',
                           'message': '' if BY_ID[lid].run else 'Not built yet.', 'progress': 0.0,
                           'passed': 0, 'failed': 0, 'checks': []} for lid in layers]}
    return ValidationRun.objects.create(layers=layers, kit_path=kit_path, options=options or {}, results=results,
                                        version=app_version(), computer=platform.node())


def execute(run):
    """Runs it to the end (in this thread)."""
    last = [0.0]

    def save(throttle=False):
        if throttle and time.monotonic() - last[0] < 0.5:
            return
        last[0] = time.monotonic()
        ValidationRun.objects.filter(pk=run.pk).update(results=run.results, passed=run.passed, failed=run.failed)

    try:
        kit_state = run.results['kit']
        try:
            kit = Kit(run.kit_path)
        except KitError as e:
            kit_state.update(status='error', message=str(e))
            raise
        if not kit.exists:
            kit_state.update(status='error', message=f'No validation kit at {run.kit_path}.')
            raise KitError(kit_state['message'])
        run.manifest_sha = kit.manifest_sha()
        ValidationRun.objects.filter(pk=run.pk).update(manifest_sha=run.manifest_sha)
        kit_state['status'] = 'running'

        def fingerprint(message, fraction):
            kit_state['message'], kit_state['progress'] = message, round(fraction, 3)
            save(throttle=True)
        checked = kit.verify(fingerprint)
        kit_state.update(status='done', files=checked, progress=1.0,
                         message=f"{sum(c['ok'] for c in checked)} of {len(checked)} files match their fingerprints")
        bad = sum(not c['ok'] for c in checked)
        run.failed += bad
        good = {c['path'] for c in checked if c['ok']}
        files = [e for e in kit.files if e['path'] in good]
        save()

        for layer in run.results['layers']:
            if run.pk in _cancel:
                break
            spec = BY_ID[layer['id']]
            if not spec.run:
                continue
            layer['status'] = 'running'
            save()
            context = Context(run, kit, files, layer, lambda throttle=False: _total_and_save(run, save, throttle))
            try:
                spec.run(context)
                layer['status'] = 'done'
                layer['progress'] = 1.0
                if not layer['message'] or layer['message'].startswith(('Reading', 'Checking')):
                    layer['message'] = f"{layer['passed']} passed, {layer['failed']} failed"
            except Exception as e:   # one layer going wrong is reported, the others still run
                layer['status'] = 'error'
                layer['message'] = f'{type(e).__name__}: {e}'
                layer['trace'] = traceback.format_exc()[-2000:]
            _total_and_save(run, save)
        if run.pk in _cancel:
            run.status = ValidationRun.CANCELLED
        elif any(layer['status'] == 'error' for layer in run.results['layers']):
            run.status = ValidationRun.ERROR
        else:
            run.status = ValidationRun.FAILED if run.failed else ValidationRun.PASSED
    except Exception as e:
        run.status = ValidationRun.ERROR
        run.results.setdefault('error', f'{type(e).__name__}: {e}')
    finally:
        _cancel.discard(run.pk)
        run.finished_at = timezone.now()
        ValidationRun.objects.filter(pk=run.pk).update(status=run.status, finished_at=run.finished_at, results=run.results,
                                                       passed=run.passed, failed=run.failed)
    return run


def _total_and_save(run, save, throttle=False):
    kit_failed = sum(not c['ok'] for c in run.results['kit'].get('files') or [])
    run.passed = sum(layer['passed'] for layer in run.results['layers'])
    run.failed = kit_failed + sum(layer['failed'] for layer in run.results['layers'])
    save(throttle)


def start(run):
    """Runs it in the background."""
    def go():
        try:
            execute(run)
        finally:
            close_old_connections()
    threading.Thread(target=go, daemon=True, name=f'validation-{run.pk}').start()


def cancel(pk):
    with _lock:
        _cancel.add(pk)


def mark_abandoned():
    """Runs left 'running' by a stopped server: they can't finish."""
    ValidationRun.objects.filter(status=ValidationRun.RUNNING).exclude(
        pk__in=[int(t.name.split('-')[1]) for t in threading.enumerate() if t.name.startswith('validation-')]
    ).update(status=ValidationRun.ERROR, finished_at=timezone.now())


def default_sweep():
    return os.path.expanduser('~/Desktop/Reports')
