from django.test import TestCase
from django.urls import reverse

from reports.models import Report, ReportGroup, ReportProbe
from reports.tests.test_create_report import management, post_data


def grid_data(probes=(), groups=(), initial_probes=0, initial_groups=0):
    """The weld form grid's POST fields: lists of dicts of column fields (may include 'id', 'DELETE')."""
    data = {}
    data.update(management('probes', len(probes), initial_probes))
    data.update(management('groups', len(groups), initial_groups))
    for prefix, columns in (('probes', probes), ('groups', groups)):
        for i, column in enumerate(columns):
            for k, v in column.items():
                data[f'{prefix}-{i}-{k}'] = v
    return data


class WeldGridTests(TestCase):
    url = reverse('create-report')

    def post(self, report=None, **grid):
        data = post_data(report=report, report_type='paut_weld')
        data.update(grid_data(**grid))
        return self.client.post(self.url, data)

    def test_new_columns_save_in_order_and_groups_use_their_probe_column(self):
        resp = self.post(
            probes=[{'kind': 'paut', 'label': '90°', 'model': '10L32-A1'},
                    {'kind': 'conv_long', 'label': '0°', 'model': 'D791'}],
            groups=[{'label': 'G1', 'probe_column': '0', 'scan': 'Sectorial'},
                    {'label': '0°', 'probe_column': '1', 'scan': 'Linear'},
                    {'label': 'Loose', 'probe_column': ''}],
        )
        report = Report.objects.get()
        self.assertRedirects(resp, f'{self.url}?loaded={report.pk}')
        self.assertEqual(list(report.probes.values_list('model', 'order', 'kind')),
                         [('10L32-A1', 0, 'paut'), ('D791', 1, 'conv_long')])
        self.assertEqual(
            [(g.label, g.order, g.probe.model if g.probe else None) for g in report.groups.all()],
            [('G1', 0, '10L32-A1'), ('0°', 1, 'D791'), ('Loose', 2, None)])

    def test_untouched_new_column_is_skipped(self):
        self.post(probes=[{'kind': 'paut', 'model': 'A'}, {'kind': 'paut'}])
        self.assertEqual(list(ReportProbe.objects.values_list('model', flat=True)), ['A'])

    def test_removed_columns_are_deleted_and_the_rest_renumbered(self):
        report = Report.objects.create(report_type='paut_weld')
        p0 = ReportProbe.objects.create(report=report, order=0, model='Drop')
        p1 = ReportProbe.objects.create(report=report, order=1, model='Keep')
        g0 = ReportGroup.objects.create(report=report, order=0, label='G', probe=p1)

        self.post(
            report,
            probes=[{'id': p0.pk, 'kind': 'paut', 'model': 'Drop', 'DELETE': 'on'},
                    {'id': p1.pk, 'kind': 'paut', 'model': 'Keep'},
                    {'kind': 'paut', 'model': 'New', 'DELETE': 'on'}],
            groups=[{'id': g0.pk, 'label': 'G', 'probe_column': '1'}],
            initial_probes=2, initial_groups=1,
        )

        self.assertEqual(list(report.probes.values_list('model', 'order')), [('Keep', 0)])
        g0.refresh_from_db()
        self.assertEqual(g0.probe, p1)

    def test_loaded_report_shows_columns_with_their_probe_choice(self):
        report = Report.objects.create(report_type='paut_weld')
        ReportProbe.objects.create(report=report, order=0, model='First')
        p1 = ReportProbe.objects.create(report=report, order=1, model='Second')
        ReportGroup.objects.create(report=report, order=0, label='G', probe=p1)

        html = self.client.get(f'{self.url}?loaded={report.pk}').content.decode()

        self.assertIn('id="probe-grid"', html)
        self.assertIn('name="probes-1-model"', html)
        self.assertIn('value="Second"', html)
        self.assertRegex(html, r'<option value="1" selected>P2</option>')
        self.assertIn('id="probes-column-template"', html)

    def test_report_with_only_columns_can_be_downloaded(self):
        report = Report.objects.create(report_type='paut_weld')
        ReportProbe.objects.create(report=report, order=0, model='P')
        html = self.client.get(f'{self.url}?loaded={report.pk}').content.decode()
        self.assertIn('id="download-link"', html)

    def test_editor_without_grid_post_leaves_columns_alone(self):
        report = Report.objects.create(report_type='paut_weld')
        ReportProbe.objects.create(report=report, order=0, model='P')
        self.client.post(self.url, post_data(report=report, report_type='paut_weld'))
        self.assertEqual(report.probes.count(), 1)
