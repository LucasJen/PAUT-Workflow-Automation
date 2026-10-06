import datetime
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from reports.forms import ReportForm
from reports.models import Report


class ReportDateDefaultTests(TestCase):
    def test_new_report_defaults_to_current_day(self):
        fake_today = datetime.date(2031, 1, 2)
        with mock.patch('reports.forms.date') as mock_date:
            mock_date.today.return_value = fake_today
            form = ReportForm()
        self.assertIn('value="2031-01-02"', str(form['report_date']))

    def test_existing_report_blank_date_is_not_defaulted(self):
        report = Report.objects.create()
        self.assertNotIn('value=', str(ReportForm(instance=report)['report_date']))

    def test_existing_report_date_renders_iso(self):
        report = Report.objects.create(report_date=datetime.date(2026, 5, 11))
        self.assertIn('value="2026-05-11"', str(ReportForm(instance=report)['report_date']))

    def test_editor_renders_saved_date_as_iso(self):
        report = Report.objects.create(report_date=datetime.date(2026, 5, 11))
        resp = self.client.get(f"{reverse('create-report')}?loaded={report.pk}")
        self.assertContains(resp, 'value="2026-05-11"')


class MediaSettingsTests(TestCase):
    def test_uploads_go_under_media_root(self):
        self.assertEqual(settings.MEDIA_URL, '/media/')
        self.assertTrue(str(settings.MEDIA_ROOT).endswith('media'))
