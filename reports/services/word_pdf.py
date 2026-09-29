"""
PDF output made by Microsoft Word itself (exact pages, table of contents and page numbers).

Uses Word through COM automation (pywin32) on the machine running the app. Every user PC
has Office; a server without Word reports word_available() == False and the app falls back
to the in-browser preview. Set REPORT_PDF_ENGINE = 'off' to disable.

Each conversion starts a separate, hidden Word instance (so documents the user has open are
never touched), updates all fields, exports to PDF and quits. Conversions are serialised with
a lock because Word automation is not safe to run in parallel.
"""
import logging
import os
import shutil
import tempfile
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

WD_EXPORT_FORMAT_PDF = 17
WD_EXPORT_OPTIMIZE_FOR_PRINT = 0
WD_EXPORT_CREATE_HEADING_BOOKMARKS = 1
WD_DO_NOT_SAVE_CHANGES = 0
WD_ALERTS_NONE = 0

_lock = threading.Lock()


class WordPdfError(Exception):
    """Word could not produce the PDF."""


def word_available():
    """True when PDF output via Word is enabled and Word is installed on this machine."""
    if getattr(settings, 'REPORT_PDF_ENGINE', 'auto') == 'off' or os.name != 'nt':
        return False
    try:
        import winreg
        import win32com.client  # noqa: F401  (pywin32 installed)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'Word.Application\CurVer'):
            return True
    except (ImportError, OSError):
        return False


def _update_fields(doc):
    """Table of contents, page count, page numbers and cross-references, in every story."""
    for toc in doc.TablesOfContents:
        toc.Update()
    for rng in doc.StoryRanges:  # main text, headers, footers, text boxes (and linked stories)
        while rng is not None:
            rng.Fields.Update()
            rng = rng.NextStoryRange
    # The TOC's page numbers can move after other fields update, so refresh it once more
    for toc in doc.TablesOfContents:
        toc.UpdatePageNumbers()


def docx_to_pdf(docx_bytes):
    """Convert .docx bytes to PDF bytes using Word. Raises WordPdfError on failure."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise WordPdfError('PDF output needs the pywin32 package (pip install pywin32).') from e

    workdir = tempfile.mkdtemp(prefix='report-pdf-')
    docx_path = os.path.join(workdir, 'report.docx')
    pdf_path = os.path.join(workdir, 'report.pdf')
    with open(docx_path, 'wb') as f:
        f.write(docx_bytes)

    with _lock:
        pythoncom.CoInitialize()  # COM must be initialised on each request thread
        word = doc = None
        try:
            word = win32com.client.DispatchEx('Word.Application')  # separate instance
            word.Visible = False
            word.DisplayAlerts = WD_ALERTS_NONE
            doc = word.Documents.Open(docx_path, ConfirmConversions=False, ReadOnly=True,
                                      AddToRecentFiles=False, Visible=False)
            _update_fields(doc)
            doc.ExportAsFixedFormat(
                OutputFileName=pdf_path,
                ExportFormat=WD_EXPORT_FORMAT_PDF,
                OpenAfterExport=False,
                OptimizeFor=WD_EXPORT_OPTIMIZE_FOR_PRINT,
                CreateBookmarks=WD_EXPORT_CREATE_HEADING_BOOKMARKS,
            )
        except Exception as e:  # COM errors come in many types
            logger.exception('Word PDF export failed')
            raise WordPdfError(f'Word could not create the PDF: {e}') from e
        finally:
            try:
                if doc is not None:
                    doc.Close(SaveChanges=WD_DO_NOT_SAVE_CHANGES)
                if word is not None:
                    word.Quit(SaveChanges=WD_DO_NOT_SAVE_CHANGES)
            except Exception:
                logger.warning('Could not close Word cleanly', exc_info=True)
            pythoncom.CoUninitialize()

    try:
        with open(pdf_path, 'rb') as f:
            return f.read()
    except OSError as e:
        raise WordPdfError('Word finished but no PDF was written.') from e
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
