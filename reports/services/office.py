"""
Shared helpers for driving Microsoft Office (Word, Excel) through COM automation (pywin32).

Office automation is not safe to run in parallel, so every Word or Excel job holds `lock`.
Set REPORT_PDF_ENGINE = 'off' to disable Office output altogether.
"""
import os
import threading

from django.conf import settings

lock = threading.Lock()


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
