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
    data.update(management('drawings', 0))
    data.update(management('people', 0))
    if columns is not None:
        data['results_columns'] = json.dumps(columns)
        data['results_rows'] = json.dumps(rows or [])
    return data


class CreateReportTests(TestCase):
    url = reverse('create-report')

    def test_new_report_saves_setups_in_order(self):
        resp = self.client.post(self.url, post_data(setups=[{'scope_model': 'A'}, {'scope_model': 'B'}]))
        report = Report.objects.get()
        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')
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

        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')
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
        # The HIC report type fixes the columns; unnamed columns are mapped by position
        from reports.report_types import HIC_RESULTS_COLUMNS
        self.assertEqual(rt.columns, [heading for _, heading in HIC_RESULTS_COLUMNS])
        self.assertEqual([r.cells[:2] for r in rt.rows.all()], [['1', '2'], ['3', '4']])

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

    def test_end_date_before_start_date_is_refused(self):
        resp = self.client.post(self.url, post_data(test_date='2026-08-25', test_end_date='2026-08-13'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'The test end date is before the start date.')
        self.assertFalse(Report.objects.exists())
        # A type that hides the end date doesn't check a value kept from before
        self.client.post(self.url, post_data(report_type='paut_weld', test_date='2026-08-25', test_end_date='2026-08-13'))
        self.assertTrue(Report.objects.exists())

    def test_loaded_report_renders_hidden_id(self):
        report = Report.objects.create()
        resp = self.client.get(f'{self.url}?loaded={report.pk}')
        self.assertContains(resp, f'name="report_id" value="{report.pk}"')

    def test_loaded_report_with_setups_has_no_blank_setup_block(self):
        report = Report.objects.create()
        resp = self.client.get(f'{self.url}?loaded={report.pk}')
        self.assertContains(resp, 'name="setups-TOTAL_FORMS" value="1"')   # none yet: one to fill in
        Setup.objects.create(report=report, title='HydroFORM')
        resp = self.client.get(f'{self.url}?loaded={report.pk}')
        self.assertContains(resp, 'name="setups-TOTAL_FORMS" value="1"')   # just its own


def png_upload(name):
    import io
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class ImageSectionTests(TestCase):
    url = reverse('create-report')

    def setUp(self):
        import tempfile, shutil
        from django.test import override_settings
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

    def test_drawings_and_scan_images_saved_with_their_kind(self):
        data = post_data(columns=['Scan ID', 'Results'], rows=[['CW1 Top', 'Blisters near ID']])
        data.update(management('drawings', 1))
        data.update({'drawings-0-caption': 'FILE DRAWING', 'drawings-0-image': png_upload('drawing.png')})
        data.update(management('images', 1))
        data.update({'images-0-scan_id': 'CW1 Top', 'images-0-image': png_upload('cw1.png')})

        resp = self.client.post(self.url, data)
        report = Report.objects.get()
        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')
        self.assertEqual(
            sorted(report.images.values_list('kind', 'caption', 'scan_id')),
            [('drawing', 'FILE DRAWING', ''), ('scan', '', 'CW1 Top')],
        )

    def test_scan_id_options_come_from_results_table(self):
        report = Report.objects.create()
        table = ResultsTable.objects.create(report=report, columns=['Scan ID', 'Results'])
        from reports.models import ResultsRow, ReportImage
        ResultsRow.objects.create(table=table, cells=['CW1 Top', 'x'], order=0)
        ResultsRow.objects.create(table=table, cells=['LS2 East', 'y'], order=1)
        ReportImage.objects.create(report=report, kind=ReportImage.SCAN, scan_id='Old ID', image='report_images/a.png')

        html = self.client.get(f'{self.url}?loaded={report.pk}').content.decode()
        self.assertIn('<option value="CW1 Top">CW1 Top</option>', html)
        self.assertIn('<option value="LS2 East">LS2 East</option>', html)
        self.assertIn('Old ID (not in results table)', html)  # renamed/removed rows keep the saved value


class GenerateReportTests(TestCase):
    def test_generate_without_setups_returns_with_message(self):
        report = Report.objects.create()
        resp = self.client.get(reverse('generate-report', args=[report.pk]), follow=True)
        self.assertContains(resp, 'Add at least one UT setup')
