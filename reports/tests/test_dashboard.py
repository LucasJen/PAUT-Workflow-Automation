from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from equipment.models import Scope
from reports.models import Report, Setup
from reports.tests.test_nde_upload import make_nde, sample_setup


class DashboardTests(TestCase):
    def test_lists_scopes_due_within_30_days_overdue_first(self):
        today = date.today()
        Scope.objects.create(model='Soon', calibration_due_date=today + timedelta(days=10))
        Scope.objects.create(model='Overdue', calibration_due_date=today - timedelta(days=3))
        Scope.objects.create(model='Later', calibration_due_date=today + timedelta(days=90))
        Scope.objects.create(model='NoDate')

        resp = self.client.get(reverse('home'))
        self.assertEqual([s.model for s in resp.context['cal_due']], ['Overdue', 'Soon'])
        self.assertEqual(resp.context['stats']['cal_due'], 2)
        self.assertContains(resp, 'Overdue by 3 days')

    def test_recent_reports_most_recently_edited_first(self):
        older = Report.objects.create(document_filename='Older')
        newer = Report.objects.create(document_filename='Newer')
        # Explicit times: consecutive saves can share a clock tick on Windows
        now = timezone.now()
        Report.objects.filter(pk=newer.pk).update(updated_at=now - timedelta(hours=1))
        Report.objects.filter(pk=older.pk).update(updated_at=now)

        resp = self.client.get(reverse('home'))
        self.assertEqual([r.pk for r in resp.context['recent_reports']][:2], [older.pk, newer.pk])
        self.assertContains(resp, f'?loaded={older.pk}')

    def test_stats_count_saved_setups_only(self):
        Setup.objects.create()
        Setup.objects.create(report=Report.objects.create())
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.context['stats']['saved_setups'], 1)


class NdePageTests(TestCase):
    def test_page_shows_drop_zone_and_file_name(self):
        resp = self.client.post(reverse('nde-upload'), {
            'nde_file': SimpleUploadedFile('weld12.nde', make_nde(sample_setup())),
        })
        self.assertContains(resp, 'id="drop-zone"')
        self.assertContains(resp, 'Values read from weld12.nde')
        self.assertContains(resp, 'id="nde-groups"')

    def test_clear_setup_links_to_fresh_import_page(self):
        resp = self.client.get(reverse('nde-upload'))
        self.assertContains(resp, f'href="{reverse("nde-upload")}" class="btn btn-secondary order-first" id="clear-setup"')
        html = resp.content.decode()
        self.assertLess(html.index('name="save_setup"'), html.index('id="clear-setup"'))  # Enter still saves

    def test_save_setup_shows_message(self):
        resp = self.client.post(reverse('nde-upload'), {'save_setup': '', 'scope_model': 'X3'}, follow=True)
        setup = Setup.objects.get()
        self.assertContains(resp, f'Setup #{setup.pk} saved.')
