"""Scan plans: circumferential beams round a pipe (long seams), flat and contoured wedges."""
import math

from django.test import TestCase
from django.urls import reverse

from equipment.models import SensitivityBlock
from reports.models import ScanPlan
from reports.services import scan_plan
from reports.services.scan_plan.beams import fan
from reports.services.scan_plan.geometry import Circle, od_radius, wrap

from .test_scan_plans import PLAN_FIELDS


def plan(**fields):
    values = dict(thickness=0.28, bevel_angle=37.5, root_gap=0.0625, root_face=0.0625, index_offset=0.5,
                  exit_point=0.45, wedge_angle=36, angle_start=40, angle_stop=70, legs=2, skew_90=True,
                  skew_270=True, beam_direction='circumferential', outside_diameter=6.625)
    values.update(fields)
    return ScanPlan(**values)


class PipeGeometryTests(TestCase):
    def test_od_from_the_plan_else_the_sensitivity_block(self):
        self.assertEqual(od_radius(plan()), 6.625 / 2)
        self.assertIsNone(od_radius(plan(beam_direction='axial')))       # a flat section
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')     # test diameter 6.625"
        self.assertEqual(od_radius(plan(outside_diameter=None, sensitivity_block=block)), 6.625 / 2)
        self.assertIsNone(od_radius(plan(outside_diameter=0.5)))         # thinner than the wall: no pipe

    def test_wrap_keeps_distance_along_the_od_and_depth(self):
        p = plan()
        x, y = wrap(p, 1.0, 0.1)
        radius = 6.625 / 2
        self.assertAlmostEqual(math.hypot(x, y - radius), radius - 0.1)    # depth below the OD
        self.assertAlmostEqual(radius * math.atan2(x, radius - y), 1.0)    # distance along the OD
        self.assertEqual(wrap(plan(beam_direction='axial'), 1.0, 0.1), (1.0, 0.1))

    def test_part_is_the_od_and_id_circles(self):
        surfaces = scan_plan.part(plan()).surfaces
        self.assertTrue(all(isinstance(s, Circle) for s in surfaces))
        self.assertEqual([s.radius for s in surfaces], [6.625 / 2, 6.625 / 2 - 0.28])

    def test_counterbore_ignored_round_a_pipe(self):
        self.assertEqual(scan_plan.weld_thickness(plan(counterbore_depth=0.1)), 0.28)


class PipeBeamTests(TestCase):
    def test_beams_bounce_between_the_id_and_od(self):
        beam = fan(plan(angle_start=45, angle_stop=45)).traces[0]
        self.assertEqual(beam.surfaces, ['back wall', 'scanning surface'])
        radius = 6.625 / 2
        centre = (0.0, radius)
        self.assertAlmostEqual(math.dist(beam.points[0], centre), radius)          # enters on the OD
        self.assertAlmostEqual(math.dist(beam.points[1], centre), radius - 0.28)   # skips off the ID
        self.assertAlmostEqual(math.dist(beam.points[2], centre), radius)          # back to the OD

    def test_convex_od_steepens_the_high_angles(self):
        beams = fan(plan()).traces
        self.assertGreater(beams[-1].refracted, 70)       # a 70 deg beam enters steeper on the curved OD
        self.assertLess(abs(beams[0].refracted - 40), 2)  # low angles barely change near the touch point
        self.assertEqual([b.angle for b in beams], sorted(b.angle for b in beams))

    def test_flat_wedge_lifts_off_contoured_does_not(self):
        flat, contoured = fan(plan()), fan(plan(wedge_contour='contoured'))
        self.assertGreater(flat.lift_off, 0)
        self.assertTrue(flat.couplant)
        self.assertEqual((contoured.lift_off, contoured.couplant), (0.0, []))
        # A flat bottom of length L on radius R: sag at the ends about L^2 / 8R
        bottom = [p for p in scan_plan.layout(plan()).wedge if abs(p[1]) < 1e-12]
        length = max(x for x, _ in bottom) - min(x for x, _ in bottom)
        self.assertAlmostEqual(flat.lift_off, length ** 2 / (8 * 6.625 / 2), places=3)

    def test_wedge_front_sits_at_the_index_offset_along_the_od(self):
        for contour in ('flat', 'contoured'):
            p = plan(wedge_contour=contour, index_offset=0.6)
            front = fan(p).front
            radius = 6.625 / 2
            along = radius * math.atan2(front[0], radius - front[1])
            self.assertAlmostEqual(along, -0.6, places=6, msg=contour)

    def test_drawing_and_coverage(self):
        p = plan()
        scene = scan_plan.build_scene(p, 2, analysis=True)
        self.assertEqual(scene.meta['od_radius'], 6.625 / 2)
        self.assertTrue(any(s.get('fill') == 'couplant' for s in scene.shapes))
        self.assertTrue(scan_plan.render_scene(scene).startswith(b'\x89PNG'))
        self.assertGreater(scan_plan.coverage(p).fraction, 0.5)


class PipeFormTests(TestCase):
    def test_circumferential_needs_an_od(self):
        resp = self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'beam_direction': 'circumferential'})
        self.assertContains(resp, "Enter the pipe&#x27;s OD")
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'beam_direction': 'circumferential',
                                                     'sensitivity_block': block.pk})
        self.assertEqual(ScanPlan.objects.get().beam_direction, 'circumferential')   # the block's OD will do

    def test_custom_od_overrides_and_is_stored_in_inches(self):
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'units': 'metric', 'thickness': '7.11',
                                                     'index_offset': '12.7', 'beam_direction': 'circumferential',
                                                     'outside_diameter': '168.28', 'wedge_contour': 'contoured'})
        saved = ScanPlan.objects.get()
        self.assertAlmostEqual(saved.outside_diameter, 6.625, places=3)
        self.assertEqual(saved.wedge_contour, 'contoured')

    def test_scenes_report_the_pipe(self):
        data = self.client.get(reverse('scan-plan-scenes'), {**PLAN_FIELDS, 'beam_direction': 'circumferential',
                                                              'outside_diameter': '6.625'}).json()
        pipe = data['pipe']
        self.assertEqual(pipe['od'], 6.625)
        self.assertGreater(pipe['refracted'][1], pipe['nominal'][1])
        self.assertTrue(pipe['lift_off_warning'])           # an SA1-size flat wedge on 6.625" lifts > 0.5 mm
        self.assertIsNone(self.client.get(reverse('scan-plan-scenes'), PLAN_FIELDS).json()['pipe'])
