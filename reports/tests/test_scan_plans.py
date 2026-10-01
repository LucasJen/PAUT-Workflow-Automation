"""Scan plans: geometry, drawing, the scan plan pages, and the weld report's Scan Plan page."""
import io
import math

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from reports.models import Report, ScanPlan, Setup
from reports.services import scan_plan
from reports.services.excel_report import weld_pages

PLAN_FIELDS = {
    'name': '6in Sch 40', 'pipe_size': '6in Sch 40', 'sides': 'both', 'legs': '2',
    'thickness': '0.28', 'bevel_angle': '37.5', 'root_gap': '0.0625', 'root_face': '0.0625', 'cap_width': '',
    'index_offset': '0.48', 'exit_point': '0.45', 'wedge_angle': '38.9',
    'angle_start': '42', 'angle_stop': '73', 'angle_step': '1', 'notes': '',
}


def make_plan(**fields):
    values = dict(name='6in', thickness=0.28, index_offset=0.48, exit_point=0.45, wedge_angle=38.9,
                  angle_start=42, angle_stop=73)
    values.update(fields)
    return ScanPlan.objects.create(**values)


class GeometryTests(TestCase):
    def test_angles_include_both_ends(self):
        plan = ScanPlan(angle_start=45, angle_stop=70, angle_step=10)
        self.assertEqual(scan_plan.angles(plan), [45, 55, 65, 70])
        self.assertEqual(scan_plan.angles(ScanPlan(angle_start=70, angle_stop=45, angle_step=12.5)), [45, 57.5, 70])

    def test_beam_bounces_off_the_back_wall(self):
        plan = ScanPlan(thickness=0.5, index_offset=1.0, exit_point=0.5, legs=2)
        start, bounce, back = scan_plan.beam_path(plan, 45)
        self.assertEqual(start, (-1.5, 0.0))
        self.assertAlmostEqual(bounce[0], -1.0)
        self.assertEqual(bounce[1], 0.5)
        self.assertAlmostEqual(back[0], -0.5)
        plan.legs = 1
        self.assertEqual(len(scan_plan.beam_path(plan, 45)), 2)

    def test_single_v_outline_and_cap_width(self):
        plan = ScanPlan(thickness=0.5, bevel_angle=45, root_gap=0.1, root_face=0.1, cap_width=None)
        (cap_x, cap_y), (land_x, land_y), (root_x, root_y) = scan_plan.weld_outline(plan)
        self.assertAlmostEqual(cap_x, -(0.05 + 0.4 * math.tan(math.radians(45))))
        self.assertEqual((cap_y, root_y), (0.0, 0.5))
        self.assertAlmostEqual(land_y, 0.4)
        self.assertAlmostEqual(scan_plan.cap_width(plan), 0.9 + 0.125)
        plan.cap_width = 1.2
        self.assertEqual(scan_plan.cap_width(plan), 1.2)

    def test_renders_both_sides_as_png(self):
        plan = make_plan()
        for side in (1, 2):
            image = Image.open(io.BytesIO(scan_plan.render_png(plan, side)))
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.width, scan_plan.WIDTH_PX)


class ScanPlanPageTests(TestCase):
    def test_list_and_new_pages(self):
        make_plan(name='Listed plan')
        self.assertContains(self.client.get(reverse('scan-plan-list')), 'Listed plan')
        self.assertContains(self.client.get(reverse('new-scan-plan')), 'id="scan-plan-preview"')

    def test_create_and_edit(self):
        resp = self.client.post(reverse('new-scan-plan'), PLAN_FIELDS)
        plan = ScanPlan.objects.get()
        self.assertRedirects(resp, reverse('edit-scan-plan', args=[plan.pk]))
        self.client.post(reverse('edit-scan-plan', args=[plan.pk]), {**PLAN_FIELDS, 'index_offset': '0.6'})
        plan.refresh_from_db()
        self.assertEqual(plan.index_offset, 0.6)

    def test_invalid_values_are_rejected(self):
        resp = self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'thickness': '0', 'angle_stop': '95'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Enter a thickness above 0.')
        self.assertContains(resp, 'Enter an angle from 0 to 89°.')
        self.assertFalse(ScanPlan.objects.exists())

    def test_live_preview_draws_unsaved_values(self):
        resp = self.client.get(reverse('scan-plan-preview'), {**PLAN_FIELDS, 'side': '2'})
        self.assertEqual(resp['Content-Type'], 'image/png')
        self.assertFalse(ScanPlan.objects.exists())
        self.assertEqual(self.client.get(reverse('scan-plan-preview'), {**PLAN_FIELDS, 'thickness': ''}).status_code, 400)

    def test_saved_plan_png(self):
        plan = make_plan()
        self.assertEqual(self.client.get(reverse('scan-plan-png', args=[plan.pk]))['Content-Type'], 'image/png')

    def test_fill_from_setup_values(self):
        Setup.objects.create(title='PAUT 1', specimen_thickness='0.280', wedge_angle='38.90',
                             angle_range='42.0° – 73.0°', angle_step='1.0')
        resp = self.client.get(reverse('new-scan-plan'))
        values = resp.context['setup_fill_values']
        self.assertEqual(list(values.values())[0]['fields'],
                         {'thickness': 0.28, 'wedge_angle': 38.9, 'angle_start': 42.0, 'angle_stop': 73.0, 'angle_step': 1.0})

    def test_duplicate_and_delete_from_list(self):
        plan = make_plan(name='Original')
        self.client.post(reverse('scan-plan-list'), {'selected': [plan.pk], 'duplicate': ''})
        self.assertTrue(ScanPlan.objects.filter(name='Original (copy)').exists())
        self.client.post(reverse('scan-plan-list'), {'selected': list(ScanPlan.objects.values_list('pk', flat=True)), 'delete': ''})
        self.assertFalse(ScanPlan.objects.exists())


class WeldReportScanPlanTests(TestCase):
    def test_scan_plan_adds_the_last_page(self):
        report = Report.objects.create(report_type='paut_weld')
        self.assertIsNone(weld_pages(report).scan_plan)
        self.assertEqual(weld_pages(report).page_count, 1)
        report.scan_plan = make_plan()
        report.save()
        pages = weld_pages(report)
        self.assertEqual(pages.scan_plan, report.scan_plan)
        self.assertEqual(pages.page_count, 2)

    def test_deleting_a_plan_keeps_the_report(self):
        report = Report.objects.create(report_type='paut_weld', scan_plan=make_plan())
        ScanPlan.objects.all().delete()
        report.refresh_from_db()
        self.assertIsNone(report.scan_plan)

    def test_editor_offers_scan_plans(self):
        make_plan(name='Pick me')
        self.assertContains(self.client.get(reverse('create-report')), 'Pick me')
