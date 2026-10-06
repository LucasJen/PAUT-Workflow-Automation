from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class MigrationDriftTests(TestCase):
    def test_models_match_migrations(self):
        """Fails if a model change is missing a migration (e.g. default_auto_field drift)."""
        out = StringIO()
        try:
            call_command('makemigrations', '--check', '--dry-run', stdout=out, stderr=out)
        except SystemExit:
            self.fail(f'Missing migrations:\n{out.getvalue()}')
