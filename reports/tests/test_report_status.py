from datetime import date

from django.test import TestCase
from django.urls import reverse

from reports.models import Report, Setup
from reports.tests.test_create_report import post_data


class ReportStatusTests(TestCase):
    url = reverse('create-report')

    def setUp(self):
        self.report = Report.objects.create(document_filename='Sent')
        Setup.objects.create(report=self.report, scope_model='A')

    def issue(self):
        return self.client.post(reverse('report-status', args=[self.report.pk]), {'action': 'issue'})

    def test_save_and_issue(self):
        resp = self.client.post(self.url, post_data(report=self.report, issue='1', client='Client'))
        self.assertRedirects(resp, f'{self.url}?loaded={self.report.pk}')
        self.report.refresh_from_db()
        self.assertEqual((self.report.status, self.report.issued_date, self.report.client),
                         (Report.ISSUED, date.today(), 'Client'))

    def test_issued_report_is_read_only(self):
        self.issue()
        resp = self.client.get(self.url, {'loaded': self.report.pk})
        self.assertContains(resp, 'Reopen for editing')
        self.assertContains(resp, '<fieldset class="plain-fieldset" disabled>')
        self.assertNotContains(resp, 'name="generate"')
        # A save posted anyway is refused
        self.client.post(self.url, post_data(report=self.report, client='Changed'))
        self.report.refresh_from_db()
        self.assertEqual(self.report.client, '')
        # The guided editor shows it read-only too
        resp = self.client.get(self.url, {'loaded': self.report.pk, 'wizard': '1'})
        self.assertRedirects(resp, f'{self.url}?loaded={self.report.pk}', fetch_redirect_response=False)

    def test_reopen(self):
        self.issue()
        self.client.post(reverse('report-status', args=[self.report.pk]), {'action': 'reopen'})
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, Report.DRAFT)
        self.client.post(self.url, post_data(report=self.report, client='Changed'))
        self.report.refresh_from_db()
        self.assertEqual(self.report.client, 'Changed')

    def test_issued_reports_are_not_deleted_from_the_list(self):
        draft = Report.objects.create(document_filename='Draft')
        self.issue()
        resp = self.client.post(reverse('report-list'), {'delete': '1', 'selected': [self.report.pk, draft.pk]},
                                follow=True)
        self.assertEqual(list(Report.objects.values_list('pk', flat=True)), [self.report.pk])
        self.assertContains(resp, '1 issued report was kept')

    def test_duplicate_of_an_issued_report_is_a_draft(self):
        self.issue()
        self.client.post(reverse('report-list'), {'duplicate': '1', 'selected': [self.report.pk]})
        copy = Report.objects.exclude(pk=self.report.pk).get()
        self.assertEqual((copy.status, copy.issued_date), (Report.DRAFT, None))

    def test_mark_issued_from_the_preview_returns_there(self):
        preview = reverse('preview-report', args=[self.report.pk])
        resp = self.client.post(reverse('report-status', args=[self.report.pk]), {'action': 'issue', 'next': preview})
        self.assertRedirects(resp, preview, fetch_redirect_response=False)
        resp = self.client.post(reverse('report-status', args=[self.report.pk]),
                                {'action': 'reopen', 'next': 'https://example.com/'})
        self.assertRedirects(resp, f'{self.url}?loaded={self.report.pk}', fetch_redirect_response=False)
