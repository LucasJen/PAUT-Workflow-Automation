import re

from django.test import TestCase
from django.urls import reverse

from equipment.models import CalibrationBlock, Encoder, Probe, Scope, SensitivityBlock
from reports.forms import ReportForm, SetupForm
from reports.models import Report, Setup


class PageSmokeTests(TestCase):
    """Every page renders inside the shared layout."""

    @classmethod
    def setUpTestData(cls):
        cls.report = Report.objects.create(document_filename='Smoke')
        cls.setup = Setup.objects.create()
        cls.objects = {
            'edit-scope': Scope.objects.create(),
            'edit-probe': Probe.objects.create(),
            'edit-cal-block': CalibrationBlock.objects.create(),
            'edit-sensitivity-block': SensitivityBlock.objects.create(),
            'edit-encoder': Encoder.objects.create(),
        }

    def urls(self):
        names = [
            'home', 'create-report', 'report-list', 'setup-list', 'nde-upload',
            'scope-list', 'probe-list', 'cal-block-list', 'sensitivity-block-list', 'encoder-list',
        ]
        urls = [reverse(n) for n in names]
        urls.append(reverse('edit-setup', args=[self.setup.pk]))
        urls.append(f"{reverse('create-report')}?loaded={self.report.pk}")
        urls += [reverse(name, args=[obj.pk]) for name, obj in self.objects.items()]
        return urls

    def test_pages_render_with_sidebar(self):
        for url in self.urls():
            with self.subTest(url=url):
                resp = self.client.get(url, follow=True)
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, 'id="sidebar"')

    def test_no_external_assets(self):
        """Everything is bundled locally so the app works without internet."""
        html = self.client.get(reverse('home')).content.decode()
        external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
        self.assertEqual(external, [])

    def test_app_assets_are_cache_busted(self):
        """App CSS/JS carry ?v=<mtime> so browsers never run a stale cached script."""
        for url in [reverse('create-report'), reverse('report-list'), reverse('nde-upload')]:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                assets = re.findall(r'(?:src|href)="(/static/reports/(?:css|js)/[^"]+)"', html)
                self.assertTrue(assets)
                unversioned = [a for a in assets if not re.search(r'\?v=\d+$', a)]
                self.assertEqual(unversioned, [])

    def test_active_nav_item(self):
        html = self.client.get(reverse('scope-list')).content.decode()
        active = re.findall(r'class="nav-item-link active" href="([^"]+)"', html)
        self.assertEqual(active, [reverse('scope-list')])

    def test_loaded_report_highlights_all_reports(self):
        html = self.client.get(f"{reverse('create-report')}?loaded={self.report.pk}").content.decode()
        active = re.findall(r'class="nav-item-link active" href="([^"]+)"', html)
        self.assertEqual(active, [reverse('report-list')])


class FormStylingTests(TestCase):
    def test_widgets_get_bootstrap_classes(self):
        form = SetupForm()
        self.assertIn('form-control', form['scope_model'].field.widget.attrs['class'])
        self.assertIn('mono', form['scope_serial'].field.widget.attrs['class'])
        self.assertNotIn('mono', form['scope_model'].field.widget.attrs['class'])

    def test_field_group_renders_label_above_with_data_field(self):
        html = ReportForm()['client'].as_field_group()
        self.assertIn('data-field="client"', html)
        self.assertLess(html.index('<label'), html.index('<input'))


class ArrowNavTests(TestCase):
    """Arrow keys move between fields (arrow_nav.js) on the report, defaults, setup and scan plan forms."""

    def test_forms_opt_in(self):
        from django.urls import reverse
        from reports.models import ScanPlan, Setup
        setup = Setup.objects.create()
        plan = ScanPlan.objects.create(name='p', thickness=0.28)
        for url in (reverse('create-report'), reverse('new-defaults', args=['paut_weld']),
                    reverse('edit-setup', args=[setup.pk]), reverse('edit-scan-plan', args=[plan.pk])):
            html = self.client.get(url).content.decode()
            self.assertRegex(html, r'<form [^>]*data-arrow-nav', url)
            self.assertIn('arrow_nav.js', html)
        # pages that share the edit page layout without opting in don't get it
        from equipment.models import Scope
        scope = Scope.objects.create()
        self.assertNotIn('data-arrow-nav', self.client.get(reverse('edit-scope', args=[scope.pk])).content.decode())
