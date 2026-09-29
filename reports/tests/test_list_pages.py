from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from equipment.models import Scope
from reports.models import Report, Setup
from reports.templatetags.ui import cal_label, cal_status


class ListPageTests(TestCase):
    def test_rows_link_to_editor_and_delete_asks_first(self):
        report = Report.objects.create(document_filename='Weld 12')
        resp = self.client.get(reverse('report-list'))
        self.assertContains(resp, f'data-href="{reverse("create-report")}?loaded={report.pk}"')
        self.assertContains(resp, 'data-confirm="Delete {count} report{s}?')
        self.assertContains(resp, f'name="selected" value="{report.pk}"')

    def test_empty_list_shows_empty_state(self):
        resp = self.client.get(reverse('probe-list'))
        self.assertContains(resp, 'class="empty-state"')
        self.assertNotContains(resp, 'id="list-table"')

    def test_bulk_delete_reports(self):
        a, b, keep = (Report.objects.create() for _ in range(3))
        self.client.post(reverse('report-list'), {'selected': [a.pk, b.pk], 'delete': ''})
        self.assertEqual(list(Report.objects.values_list('pk', flat=True)), [keep.pk])

    def test_duplicate_setup(self):
        setup = Setup.objects.create(scope_model='X3')
        self.client.post(reverse('setup-list'), {'selected': [setup.pk], 'duplicate': ''})
        self.assertEqual(Setup.objects.filter(scope_model='X3').count(), 2)

    def test_scope_list_shows_due_badge(self):
        Scope.objects.create(model='X3', calibration_due_date=date.today() + timedelta(days=5))
        resp = self.client.get(reverse('scope-list'))
        self.assertContains(resp, 'badge-due due-soon')
        self.assertContains(resp, 'Due in 5 days')


class CalStatusTests(SimpleTestCase):
    def test_status(self):
        today = date.today()
        self.assertEqual(cal_status(None), '')
        self.assertEqual(cal_status(today - timedelta(days=1)), 'overdue')
        self.assertEqual(cal_status(today), 'soon')
        self.assertEqual(cal_status(today + timedelta(days=30)), 'soon')
        self.assertEqual(cal_status(today + timedelta(days=31)), 'ok')

    def test_label(self):
        today = date.today()
        self.assertEqual(cal_label(today - timedelta(days=1)), 'Overdue by 1 day')
        self.assertEqual(cal_label(today), 'Due today')
        self.assertEqual(cal_label(today + timedelta(days=2)), 'Due in 2 days')
