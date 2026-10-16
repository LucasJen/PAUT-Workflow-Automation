"""L5 export: every report type's columns take the indication's values unchanged - and nothing is left behind."""
from unittest import mock

from django.test import TestCase

from analysis.services import report_export
from reports.models import Report, ResultsRow
from validation.checks import export


class Context:
    def __init__(self):
        self.out, self.options = [], {}

    def emit(self, c):
        self.out.append(c)


class ExportTests(TestCase):
    def test_every_report_type_passes_and_nothing_is_kept(self):
        context = Context()
        export.run(context)
        self.assertTrue(context.out)
        self.assertEqual([c['subject'] for c in context.out if not c['passed']], [])
        self.assertEqual((Report.objects.count(), ResultsRow.objects.count()), (0, 0))

    def test_lengths_rounded_to_two_places_fail(self):
        with mock.patch.object(report_export, '_length', lambda m, units: '' if m is None else f'{m / 0.0254:.2f}'):
            context = Context()
            export.run(context)
        self.assertTrue(any(not c['passed'] for c in context.out))
