import json

from django.test import TestCase
from django.urls import reverse

from reports.models import Report, Setup, ResultsTable


def management(prefix, total, initial=0):
    return {
        f'{prefix}-TOTAL_FORMS': str(total),
        f'{prefix}-INITIAL_FORMS': str(initial),
        f'{prefix}-MIN_NUM_FORMS': '0',
        f'{prefix}-MAX_NUM_FORMS': '1000',
    }


def post_data(report=None, setups=(), columns=None, rows=None, **fields):
    """Builds a create-report POST body. `setups` is a list of dicts of setup fields (may include 'id')."""
    data = {'report_id': report.pk if report else '', 'document_filename': 'Test Report'}
    data.update(fields)
    initial = sum(1 for s in setups if s.get('id'))
    data.update(management('setups', len(setups), initial))
    for i, s in enumerate(setups):
        for k, v in s.items():
            data[f'setups-{i}-{k}'] = v
    data.update(management('images', 0))
    if columns is not None:
        data['results_columns'] = json.dumps(columns)
        data['results_rows'] = json.dumps(rows or [])
    return data


class CreateReportTests(TestCase):
    url = reverse('create-report')

    def test_new_report_saves_setups_in_order(self):
        resp = self.client.post(self.url, post_data(setups=[{'scope_model': 'A'}, {'scope_model': 'B'}]))
        self.assertRedirects(resp, reverse('report-list'))
        report = Report.objects.get()
        self.assertEqual(
            list(report.setups.order_by('order').values_list('scope_model', 'order')),
            [('A', 0), ('B', 1)],
        )

    def test_saving_loaded_report_updates_instead_of_duplicating(self):
        report = Report.objects.create(document_filename='Existing')
        setup = Setup.objects.create(report=report, scope_model='Old')

        resp = self.client.post(self.url, post_data(
            report=report, client='New Client',
            setups=[{'id': setup.pk, 'report': report.pk, 'scope_model': 'Updated'}],
        ))

        self.assertRedirects(resp, reverse('report-list'))
        self.assertEqual(Report.objects.count(), 1)
        report.refresh_from_db()
        self.assertEqual(report.client, 'New Client')
        self.assertEqual(list(report.setups.values_list('scope_model', flat=True)), ['Updated'])

    def test_removed_setup_is_deleted(self):
        report = Report.objects.create()
        keep = Setup.objects.create(report=report, scope_model='Keep', order=0)
        drop = Setup.objects.create(report=report, scope_model='Drop', order=1)

        self.client.post(self.url, post_data(report=report, setups=[
            {'id': drop.pk, 'report': report.pk, 'scope_model': 'Drop', 'DELETE': 'on'},
            {'id': keep.pk, 'report': report.pk, 'scope_model': 'Keep'},
        ]))

        self.assertEqual(list(report.setups.values_list('scope_model', 'order')), [('Keep', 0)])

    def test_results_table_is_replaced_on_resave(self):
        report = Report.objects.create()
        self.client.post(self.url, post_data(report=report, columns=['A'], rows=[['1']]))
        self.client.post(self.url, post_data(report=report, columns=['X', 'Y'], rows=[['1', '2'], ['3', '4']]))

        rt = ResultsTable.objects.get(report=report)
        self.assertEqual(rt.columns, ['X', 'Y'])
        self.assertEqual([r.cells for r in rt.rows.all()], [['1', '2'], ['3', '4']])

    def test_removing_all_columns_deletes_results_table(self):
        report = Report.objects.create()
        self.client.post(self.url, post_data(report=report, columns=['A'], rows=[['1']]))
        self.client.post(self.url, post_data(report=report, columns=[], rows=[]))
        self.assertFalse(ResultsTable.objects.filter(report=report).exists())

    def test_invalid_setup_saves_nothing(self):
        too_long = 'x' * 500
        resp = self.client.post(self.url, post_data(setups=[{'scope_model': too_long}]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Report.objects.exists())

    def test_malformed_results_saves_nothing(self):
        data = post_data(setups=[{'scope_model': 'A'}])
        data['results_columns'] = '{not json'
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Report.objects.exists())

    def test_loaded_report_renders_hidden_id(self):
        report = Report.objects.create()
        resp = self.client.get(f'{self.url}?loaded={report.pk}')
        self.assertContains(resp, f'name="report_id" value="{report.pk}"')


class GenerateReportTests(TestCase):
    def test_generate_without_setups_returns_with_message(self):
        report = Report.objects.create()
        resp = self.client.get(reverse('generate-report', args=[report.pk]), follow=True)
        self.assertContains(resp, 'Add at least one UT setup')
