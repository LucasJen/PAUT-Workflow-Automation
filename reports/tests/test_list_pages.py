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

    def test_bulk_actions_live_in_the_sticky_header(self):
        Report.objects.create()
        html = self.client.get(reverse('report-list')).content.decode()
        header_start = html.index('id="list-header"')
        header = html[header_start:html.index('id="list-form"')]
        self.assertIn('class="page-header list-header"', html[header_start - 60:header_start + 20])
        for part in ('id="bulk-bar"', 'id="clear-selection"', 'name="delete"', 'name="duplicate"', 'id="list-search"'):
            self.assertIn(part, header)

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

    def test_setups_page_leaves_report_setups_alone(self):
        report = Report.objects.create()
        in_report = Setup.objects.create(report=report, scope_model='In report')
        saved = Setup.objects.create(scope_model='Saved')
        resp = self.client.get(reverse('setup-list'))
        self.assertContains(resp, 'Saved')
        self.assertNotContains(resp, 'In report')
        self.client.post(reverse('setup-list'), {'selected': [in_report.pk, saved.pk], 'delete': ''})
        self.assertEqual(list(Setup.objects.values_list('pk', flat=True)), [in_report.pk])
        resp = self.client.post(reverse('setup-list'), {'selected': [in_report.pk], 'duplicate': ''})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(report.setups.count(), 1)

    def test_new_pages_only_create_on_save(self):
        from equipment.models import CalibrationBlock, Encoder, Probe, SensitivityBlock
        for name, model in (('new-setup', Setup), ('new-scope', Scope), ('new-probe', Probe),
                            ('new-cal-block', CalibrationBlock), ('new-sensitivity-block', SensitivityBlock),
                            ('new-encoder', Encoder)):
            before = model.objects.count()
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
            self.assertEqual(model.objects.count(), before, name)
            self.client.post(reverse(name), {'delete': ''})
            self.assertEqual(model.objects.count(), before, name)
        self.client.post(reverse('new-scope'), {'model': 'X3 new', 'manufacturer': 'Evident'})
        self.assertTrue(Scope.objects.filter(model='X3 new').exists())

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
