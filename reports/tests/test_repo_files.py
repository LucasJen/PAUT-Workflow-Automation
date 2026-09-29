from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class RequirementsFileTests(SimpleTestCase):
    def test_requirements_is_utf8_text(self):
        """pip can't read UTF-16 (e.g. from `pip freeze > requirements.txt` in Windows PowerShell)."""
        raw = (Path(settings.BASE_DIR) / 'requirements.txt').read_bytes()
        self.assertNotIn(b'\x00', raw, 'requirements.txt is UTF-16; re-save it as UTF-8')
        lines = [line for line in raw.decode('utf-8').splitlines() if line.strip()]
        self.assertTrue(all('==' in line for line in lines), lines)
        self.assertIn('docxtpl', raw.decode('utf-8'))
