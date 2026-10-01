"""Scan plans: geometry, drawing, the scan plan pages, and the weld report's Scan Plan page."""
import io
import math

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from equipment.compat import BEAMTOOL_SOURCE
from equipment.models import ProbeModel, SensitivityBlock, WedgeModel
from reports.models import Report, ScanPlan, Setup
from reports.services import scan_plan
from reports.services.excel_report import weld_pages

PLAN_FIELDS = {
    'name': '6in Sch 40', 'pipe_size': '6in Sch 40', 'sides': 'both', 'legs': '2',
    'thickness': '0.28', 'bevel_angle': '37.5', 'root_gap': '0.0625', 'root_face': '0.0625', 'cap_width': '',
    'index_offset': '0.48', 'exit_point': '0.45', 'wedge_angle': '38.9',
    'angle_start': '42', 'angle_stop': '73', 'angle_step': '1', 'notes': '',
    'first_element': '1', 'aperture_elements': '', 'shear_velocity': '0.1276',
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
                         {'thickness': 0.28, 'angle_start': 42.0, 'angle_stop': 73.0, 'angle_step': 1.0})
        # the wedge angle comes only from the wedge selector

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


class ExactGeometryTests(TestCase):
    """Exit points from the probe (pitch) and wedge geometry, by Snell's law."""

    def plan(self, **fields):
        probe = ProbeModel.objects.get(model='10L32-A1')
        wedge = WedgeModel.objects.get(model='SA1-N60S')
        wedge.velocity, wedge.primary_offset, wedge.first_element_height = 2330.0, -24.0, 8.382
        wedge.save()
        values = dict(probe_model=probe, wedge_model=wedge, first_element=1, aperture_elements=27,
                      angle_start=42, angle_stop=73, angle_step=1)
        values.update(fields)
        return make_plan(**values)

    def test_sketch_only_without_probe_and_wedge(self):
        plan = make_plan()
        self.assertIsNone(scan_plan.catalogue_layout(plan))
        self.assertEqual(set(scan_plan.layout(plan).exits.values()), {scan_plan.exit_x(plan)})

    def test_catalogue_sizes_with_estimates_when_geometry_is_incomplete(self):
        """Seeded wedges lack velocity / primary offset; the drawing still uses their size."""
        small = make_plan(probe_model=ProbeModel.objects.get(model='10L32-A1'),
                          wedge_model=WedgeModel.objects.get(model='SA1-N60S'))
        large = make_plan(probe_model=ProbeModel.objects.get(model='5L64-A2'),
                          wedge_model=WedgeModel.objects.get(model='SA2-N55S'))
        a, b = scan_plan.layout(small), scan_plan.layout(large)
        self.assertFalse(a.exact)
        self.assertIn('wedge velocity', a.estimated)
        self.assertIn('first element position', a.estimated)
        self.assertNotIn('wedge angle', a.estimated)          # SA1-N60S has 38.9°
        self.assertIn('wedge angle', b.estimated)              # worked out from 55° refracted
        width = lambda lay: max(x for x, _ in lay.wedge) - min(x for x, _ in lay.wedge)
        self.assertAlmostEqual(width(a), 30 / 25.4)
        self.assertAlmostEqual(width(b), 69 / 25.4)
        self.assertGreater(len(set(round(x, 6) for x in a.exits.values())), 1)  # per-angle exit points

    def test_exit_points_follow_snells_law(self):
        plan = self.plan()
        lay = scan_plan.exact_layout(plan)
        self.assertTrue(lay.exact)
        cx, cy = lay.source
        # Aperture centre: element 14 (1 + 26/2) up the face from the first element
        s = 13 * 0.31 / 25.4
        a = math.radians(38.9)
        self.assertAlmostEqual(cx, -0.48 - 24 / 25.4 + s * math.cos(a))
        self.assertAlmostEqual(-cy, 8.382 / 25.4 + s * math.sin(a))
        for angle, x in lay.exits.items():
            incident = math.asin(2330 / 25400 / 0.1276 * math.sin(math.radians(angle)))
            self.assertAlmostEqual(x, cx - cy * math.tan(incident))
        # Higher refracted angles leave the wedge further forward
        xs = [lay.exits[a] for a in sorted(lay.exits)]
        self.assertEqual(xs, sorted(xs))

    def test_angles_past_critical_have_no_beam(self):
        plan = self.plan(shear_velocity=0.09, angle_start=40, angle_stop=89)
        exits = scan_plan.exact_layout(plan).exits
        self.assertIn(40, exits)
        self.assertNotIn(89, exits)

    def test_longitudinal_wedge_uses_the_blocks_l_wave_velocity(self):
        plan = self.plan(sensitivity_block=SensitivityBlock.objects.get(pipe_size='6in Sch 40'))
        wedge = plan.wedge_model
        self.assertEqual(scan_plan.part_velocity(plan, wedge), 0.1276)
        wedge.wave_type = 'LW'
        self.assertEqual(scan_plan.part_velocity(plan, wedge), 0.232)

    def test_renders_exact_layout(self):
        image = Image.open(io.BytesIO(scan_plan.render_png(self.plan(), 2)))
        self.assertEqual(image.width, scan_plan.WIDTH_PX)

    def test_page_offers_block_and_wedge_values(self):
        values = self.client.get(reverse('new-scan-plan')).context['catalogue_fill_values']
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        self.assertEqual(values['sensitivity_block'][block.pk],
                         {'pipe_size': '6in Sch 40', 'thickness': 0.28, 'bevel_angle': 37.0, 'shear_velocity': 0.128})
        wedge = WedgeModel.objects.get(model='SA1-N60S')
        self.assertEqual(values['wedge_model'][wedge.pk], {'wedge_angle': 38.9})


class WedgeForProbeTests(TestCase):
    def test_mismatched_wedge_is_rejected(self):
        probe = ProbeModel.objects.get(model='10L32-A1')
        wrong = WedgeModel.objects.get(model='SA2-N55S')
        resp = self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'probe_model': probe.pk, 'wedge_model': wrong.pk})
        self.assertContains(resp, 'SA2-N55S fits A2 probes, not 10L32-A1.')
        self.assertFalse(ScanPlan.objects.exists())

    def test_matching_wedge_is_accepted(self):
        probe = ProbeModel.objects.get(model='10L32-A1')
        wedge = WedgeModel.objects.get(model='SA1-N60S')
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'probe_model': probe.pk, 'wedge_model': wedge.pk})
        self.assertEqual(ScanPlan.objects.get().wedge_model, wedge)

    def test_wedges_endpoint_lists_the_probes_wedges(self):
        probe = ProbeModel.objects.get(model='10L32-A1')
        WedgeModel.objects.create(model='SA1-N60S 10L32', probe_series='A1', probe_fit='10L32', source=BEAMTOOL_SOURCE)
        WedgeModel.objects.create(model='SA1-N60S 5L16', probe_series='A1', probe_fit='5L16', source=BEAMTOOL_SOURCE)
        names = [name for _, name in self.client.get(reverse('scan-plan-wedges'), {'probe': probe.pk}).json()['wedges']]
        self.assertIn('SA1-N60S 10L32', names)
        self.assertIn('SA1-N60S', names)
        self.assertNotIn('SA1-N60S 5L16', names)
        self.assertNotIn('SA2-N55S', names)
        self.assertEqual(self.client.get(reverse('scan-plan-wedges')).json(), {'wedges': []})

    def test_wedge_list_on_the_page_follows_the_probe(self):
        WedgeModel.objects.create(model='SA1-N60S 10L32', probe_series='A1', probe_fit='10L32', source=BEAMTOOL_SOURCE)
        probe = ProbeModel.objects.get(model='10L32-A1')
        plan = make_plan(probe_model=probe)
        page = self.client.get(reverse('edit-scan-plan', args=[plan.pk])).content.decode()
        self.assertIn('SA1-N60S 10L32', page)
        self.assertNotIn('SA2-N55S', page)
        blank = self.client.get(reverse('new-scan-plan')).content.decode()
        self.assertNotIn('SA1-N60S 10L32', blank)  # library wedges wait for a probe
        self.assertIn('Pick a probe first', blank)


class EstimatedPositionTests(TestCase):
    def test_probe_face_starts_near_the_heel_and_probe_stays_on_the_wedge(self):
        wedge = WedgeModel.objects.get(model='SA1-N60S')
        wedge.first_element_height = 8.382
        wedge.save()
        plan = make_plan(probe_model=ProbeModel.objects.get(model='10L32-A1'), wedge_model=wedge, aperture_elements=27)
        lay = scan_plan.layout(plan)
        back = min(x for x, _ in lay.wedge)
        heel = max(-y for x, y in lay.wedge if abs(x - back) < 1e-9)
        self.assertAlmostEqual(heel * 25.4, 16 * scan_plan.HEEL_FRACTION)
        self.assertGreaterEqual(min(x for x, _ in lay.face), back - 1e-9)  # the probe sits on the wedge's face
        # The first element sits at its catalogue height (8.382 mm) on that face
        a = math.radians(38.9)
        s = 13 * 0.31 / 25.4
        self.assertAlmostEqual(-lay.source[1] * 25.4, 8.382 + s * math.sin(a) * 25.4)


class BeamtoolGeometryTests(TestCase):
    def test_library_geometry_reproduces_the_omniscan_scan_plan(self):
        """
        SA1-N60S 10L32 from the Beamtool library (X 27.19, Z 5.15, 39 deg, 2330 m/s) with elements
        1-27 of a 10L32-A1 puts the beams where the reference report's OmniScan scan plan shows
        them: aperture centre about 23.5 mm behind the wedge front at 7.5 mm, exits 16.4-19.3 mm.
        """
        wedge = WedgeModel.objects.create(model='SA1-N60S 10L32', probe_series='A1', probe_fit='10L32',
                                          wedge_angle=39.0, velocity=2330.0, primary_offset=-27.19,
                                          first_element_height=5.15, length=30.38, height=16.41)
        plan = make_plan(probe_model=ProbeModel.objects.get(model='10L32-A1'), wedge_model=wedge,
                         aperture_elements=27, angle_start=42, angle_stop=73)
        lay = scan_plan.layout(plan)
        self.assertTrue(lay.exact)

        def behind(x):
            return (-plan.index_offset - x) * 25.4
        self.assertAlmostEqual(behind(lay.source[0]), 23.5, delta=1.0)
        self.assertAlmostEqual(-lay.source[1] * 25.4, 7.5, delta=0.5)
        exits = [behind(x) for x in lay.exits.values()]
        self.assertAlmostEqual(min(exits), 16.4, delta=0.7)
        self.assertAlmostEqual(max(exits), 19.3, delta=0.7)


class ScanPlanFormLayoutTests(TestCase):
    def test_layout_and_defaults(self):
        from reports.forms import ScanPlanForm
        form = ScanPlanForm()
        sections = {title: [f.name for f in fields] for title, fields in form.fieldsets()}
        self.assertIn('index_offset', sections['Weld (inches, degrees)'])
        self.assertEqual(sections['Beams'], ['angle_start', 'angle_stop', 'legs', 'angle_step'])
        hidden = {f.name for f in form.hidden_fields()}
        self.assertEqual(hidden, {'wedge_angle', 'exit_point'})
        self.assertFalse(any(name in hidden for names in sections.values() for name in names))
        self.assertEqual((form['angle_start'].initial, form['angle_stop'].initial), (40.0, 70.0))
        page = self.client.get(reverse('new-scan-plan')).content.decode()
        self.assertIn('type="hidden" name="wedge_angle"', page)
        self.assertIn('type="hidden" name="exit_point"', page)

    def test_wedge_selector_fills_wedge_angle_and_exit_point(self):
        """SA1-N60S 10L32: 39 deg, X 27.19, Z 5.15 mm; the 60 deg beam leaves about 0.85 in behind the front."""
        wedge = WedgeModel.objects.create(model='SA1-N60S 10L32', probe_series='A1', probe_fit='10L32', wave_type='SW',
                                          refracted_angle=60.0, wedge_angle=39.0, velocity=2330.0,
                                          primary_offset=-27.19, first_element_height=5.15)
        values = self.client.get(reverse('new-scan-plan')).context['catalogue_fill_values']['wedge_model'][wedge.pk]
        incident = math.asin(2330 / 25400 / 0.1276 * math.sin(math.radians(60)))
        expected = round((27.19 - 5.15 * math.tan(incident)) / 25.4, 3)
        self.assertEqual(values, {'wedge_angle': 39.0, 'exit_point': expected})
