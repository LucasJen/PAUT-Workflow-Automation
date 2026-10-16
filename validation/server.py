"""
The app served in-process on a private port for the browser checks: the real pages and static files,
the same code and settings as the running app, with the kit's folder allowed for opening .nde files
while it runs. Works from the Validation page and from the command line alike.
"""
import contextlib

from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.test import override_settings
from django.test.testcases import LiveServerThread


@contextlib.contextmanager
def live_server(kit_root):
    """Yields the base URL (http://127.0.0.1:port) of the app served in this process."""
    roots = list(getattr(settings, 'ANALYSIS_EXTRA_ROOTS', [])) + [kit_root]
    hosts = list(settings.ALLOWED_HOSTS) + ['127.0.0.1']
    with override_settings(ANALYSIS_EXTRA_ROOTS=roots, ALLOWED_HOSTS=hosts):
        thread = LiveServerThread('127.0.0.1', StaticFilesHandler, connections_override={}, port=0)
        thread.daemon = True
        thread.start()
        thread.is_ready.wait()
        if thread.error:
            raise thread.error
        try:
            yield f'http://127.0.0.1:{thread.port}'
        finally:
            thread.terminate()
