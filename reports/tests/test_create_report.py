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

    def test_new_report_of_a_chosen_type_starts_from_its_defaults(self):
        from reports.models import ReportDefaults
        ReportDefaults.objects.create(report_type='paut_corrosion', in_use=True,
                                      report_values={'client': 'Short Form Client'})
        resp = self.client.get(self.url, {'type': 'paut_corrosion'})
        form = resp.context['form']
        self.assertEqual(form['report_type'].value(), 'paut_corrosion')
        self.assertEqual(form['client'].value(), 'Short Form Client')
        # An unknown type falls back to the default type
        resp = self.client.get(self.url, {'type': 'nope'})
        self.assertEqual(resp.context['form']['report_type'].value(), 'paut_long')

    def test_new_report_menu_lists_every_type(self):
        resp = self.client.get(reverse('report-list'))
        for key in ('paut_long', 'paut_weld', 'paut_corrosion'):
            self.assertContains(resp, f'?type={key}')

    def test_report_list_columns_and_filters(self):
        Report.objects.create(document_filename='Weld', report_type='paut_weld', client='Acme', status='issued')
        Report.objects.create(document_filename='Corrosion', report_type='paut_corrosion', client=' acme 2 ')
        resp = self.client.get(reverse('report-list'))
        self.assertEqual(resp.context['clients'], ['Acme', 'acme 2'])
        self.assertContains(resp, 'data-type="paut_weld"')
        self.assertContains(resp, 'data-status="issued"')
        self.assertContains(resp, 'data-client="acme 2"')
        self.assertContains(resp, 'PAUT weld (Excel)')

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


class StaleSaveTests(TestCase):
    url = reverse('create-report')

    def test_page_carries_the_version_it_loaded(self):
        report = Report.objects.create(document_filename='Existing')
        page = self.client.get(self.url, {'loaded': report.pk})
        self.assertEqual(page.context['loaded_version'], report.updated_at.isoformat())
        self.assertContains(page, f'name="loaded_version" value="{report.updated_at.isoformat()}"')

    def test_save_over_a_newer_version_is_held_once(self):
        from datetime import timedelta
        report = Report.objects.create(document_filename='Existing', client='Mine')
        opened = report.updated_at.isoformat()
        # Another tab saves later
        Report.objects.filter(pk=report.pk).update(client='Other tab', updated_at=report.updated_at + timedelta(minutes=5))

        resp = self.client.post(self.url, post_data(report=report, client='This tab', loaded_version=opened))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'saved from another tab or window')
        self.assertContains(resp, 'value="This tab"')   # this tab's entries stay on the page
        report.refresh_from_db()
        self.assertEqual(report.client, 'Other tab')
        # Save again: the page now holds the newer version, so it goes through
        resp = self.client.post(self.url, post_data(report=report, client='This tab',
                                                    loaded_version=resp.context['loaded_version']))
        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')
        report.refresh_from_db()
        self.assertEqual(report.client, 'This tab')

    def test_same_version_saves(self):
        report = Report.objects.create(document_filename='Existing')
        resp = self.client.post(self.url, post_data(report=report, client='X', loaded_version=report.updated_at.isoformat()))
        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')


class KeptUploadTests(TestCase):
    url = reverse('create-report')
    setUp = ImageSectionTests.setUp   # a temporary MEDIA_ROOT

    def test_pictures_survive_a_failed_save(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        kept_dir = Path(tempfile.mkdtemp())
        patch = mock.patch('reports.services.kept_uploads.kept_root', return_value=kept_dir)
        patch.start()
        self.addCleanup(patch.stop)

        data = post_data(columns=['Scan ID', 'Results'], rows=[['CW1 Top', 'x']],
                         test_date='2026-10-09', test_end_date='2026-10-01')   # refused: end before start
        data.update(management('drawings', 1))
        data.update({'drawings-0-caption': 'D1', 'drawings-0-image': png_upload('drawing.png')})
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Report.objects.exists())
        kept = resp.context['kept_uploads']
        self.assertEqual([(field, name) for field, _, name in kept], [('drawings-0-image', 'drawing.png')])
        self.assertContains(resp, 'name="kept_upload"')

        # Fixed and saved again without choosing the picture again: it's saved
        data = post_data(columns=['Scan ID', 'Results'], rows=[['CW1 Top', 'x']], test_date='2026-10-09')
        data.update(management('drawings', 1))
        data.update({'drawings-0-caption': 'D1', 'kept_upload': [f'{field}|{ref}' for field, ref, _ in kept]})
        resp = self.client.post(self.url, data)
        report = Report.objects.get()
        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')
        self.assertEqual(list(report.images.values_list('caption', flat=True)), ['D1'])
        self.assertEqual(list(kept_dir.iterdir()), [])   # cleared once saved

    def test_bad_references_are_ignored(self):
        from django.http import QueryDict
        from django.utils.datastructures import MultiValueDict
        from reports.services.kept_uploads import with_kept
        post = QueryDict(mutable=True)
        post.setlist('kept_upload', ['drawings-0-image|../../etc/passwd', 'x|' + 'a' * 32 + '/../secret'])
        self.assertEqual(dict(with_kept(post, MultiValueDict())), {})
