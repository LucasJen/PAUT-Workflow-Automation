"""
Shared helpers for driving Microsoft Office (Word, Excel) through COM automation (pywin32).

Office automation is not safe to run in parallel, so every Word or Excel job runs in
office_session(), which holds `lock`. A job that hangs (e.g. on a prompt the hidden Word / Excel
shows) would hold it for good, so the session waits at most LOCK_WAIT seconds for the lock and
closes the Office process its job started once the job has run JOB_LIMIT seconds.
Set REPORT_PDF_ENGINE = 'off' to disable Office output altogether.
"""
import csv
import io
import logging
import os
import signal
import subprocess
import threading
from contextlib import contextmanager

from django.conf import settings

logger = logging.getLogger(__name__)

lock = threading.Lock()
LOCK_WAIT = 120     # seconds a job waits for the one before it
JOB_LIMIT = 180     # seconds a job may take before its Word / Excel is closed


def office_app_available(prog_id):
    """True when Office output is enabled and the COM server `prog_id` (e.g. 'Excel.Application') is installed."""
    if getattr(settings, 'REPORT_PDF_ENGINE', 'auto') == 'off' or os.name != 'nt':
        return False
    try:
        import winreg
        import win32com.client  # noqa: F401  (pywin32 installed)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf'{prog_id}\CurVer'):
            return True
    except (ImportError, OSError):
        return False


def running_pids(exe):
    """Process ids of the running `exe` (e.g. 'EXCEL.EXE'), from Windows' tasklist."""
    try:
        out = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {exe}', '/FO', 'CSV', '/NH'],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {int(row[1]) for row in csv.reader(io.StringIO(out)) if len(row) > 1 and row[1].isdigit()}


def kill(pid):
    try:
        os.kill(pid, signal.SIGTERM)   # TerminateProcess on Windows
    except OSError:
        pass


class Watchdog:
    """
    Closes the Office process a job started if the job takes longer than `limit` seconds. The
    job calls started() right after launching Word / Excel: the processes that appeared since the
    session began are its own (jobs run one at a time), so a Word / Excel the user has open is
    never touched.
    """

    def __init__(self, exe, limit):
        self.exe, self.limit = exe, limit
        self.before = running_pids(exe)
        self.timer = None
        self.fired = False

    def started(self):
        own = running_pids(self.exe) - self.before
        if not own:
            return
        self.timer = threading.Timer(self.limit, self._fire, args=(own,))
        self.timer.daemon = True
        self.timer.start()

    def _fire(self, pids):
        self.fired = True
        logger.error('%s took over %s s; closing process(es) %s', self.exe, self.limit, sorted(pids))
        for pid in pids:
            kill(pid)

    def cancel(self):
        if self.timer is not None:
            self.timer.cancel()


@contextmanager
def office_session(exe, app_name, error_class):
    """
    One Word / Excel job: holds the lock (raising `error_class` when the job before it is still
    going after LOCK_WAIT seconds) and initialises COM for this thread. Yields a Watchdog: call
    its started() after launching the application, and check `fired` when the job fails.
    """
    import pythoncom
    if not lock.acquire(timeout=LOCK_WAIT):
        raise error_class(f'{app_name} is still busy with another report. Try again in a minute.')
    watchdog = None
    try:
        pythoncom.CoInitialize()  # COM must be initialised on each request thread
        try:
            watchdog = Watchdog(exe, JOB_LIMIT)
            yield watchdog
        finally:
            if watchdog is not None:
                watchdog.cancel()
            pythoncom.CoUninitialize()
    finally:
        lock.release()


def timed_out_message(app_name):
    return (f"{app_name} didn't finish within {JOB_LIMIT // 60} minutes (it may have been waiting on a "
            f'hidden prompt) and was closed. Try again.')
