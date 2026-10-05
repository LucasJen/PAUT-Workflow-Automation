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


class ReflectorTests(TestCase):
    from reports.services.scan_plan import reflectors as R

    def flat_plan(self, items, **fields):
        return plan(beam_direction='axial', index_offset=0.35, angle_start=40, angle_stop=70,
                    reflectors=self.R.clean(items, 0.28), **fields)

    def test_clean_checks_and_drops_unused_values(self):
        items = self.R.clean([{'kind': 'sidewall', 'side': '270', 'depth': '0.1', 'size': '0.1', 'distance': '9'}])
        self.assertEqual(items, [{'kind': 'sidewall', 'label': 'LOF 1', 'side': 270, 'depth': 0.1, 'size': 0.1}])
        for bad, message in (([{'kind': 'x'}], 'pick a type'),
                             ([{'kind': 'sdh', 'distance': 0, 'depth': 0.1}], 'enter its size'),
                             ([{'kind': 'sdh', 'distance': 0, 'depth': 0.5, 'size': 0.06}], 'past the wall')):
            with self.assertRaisesMessage(ValueError, message):
                self.R.clean(bad, 0.28)

    def test_hole_hit_by_the_beams_through_it(self):
        p = self.flat_plan([{'kind': 'sdh', 'side': 90, 'distance': 0.1, 'depth': 0.14, 'size': 0.0625}])
        scene = scan_plan.build_scene(p, analysis=True)
        (result,) = scene.meta['reflectors']
        self.assertTrue(result['hits'])
        best = result['best']
        self.assertLess(best['miss'], 0.0625 / 2)
        # Every listed beam really passes within the hole's radius
        for beam in (s for s in scene.shapes if s.get('group') == 'beam' and 'hits' in s.get('data', {})):
            self.assertEqual(beam['data']['hits'][0]['label'], 'SDH 1')

    def test_planar_flaw_square_on_beam_is_best(self):
        # A flaw tilted 30 deg towards the C/L on the 90 side is square-on to a ~60 deg first-leg beam
        p = self.flat_plan([{'kind': 'flaw', 'side': 90, 'distance': 0.05, 'depth': 0.14, 'size': 0.1, 'angle': -30}])
        (result,) = scan_plan.build_scene(p, analysis=True).meta['reflectors']
        self.assertTrue(result['hits'])
        self.assertLess(result['best']['incidence'], result['hits'][0]['incidence'] + 1e-9)

    def test_reflector_behind_the_wedge_is_not_reached(self):
        p = self.flat_plan([{'kind': 'od_notch', 'side': 90, 'distance': 1.5, 'size': 0.04}])
        (result,) = scan_plan.build_scene(p, analysis=True).meta['reflectors']
        self.assertEqual((result['hits'], result['best']), ([], None))

    def test_mirrored_drawing_puts_reflectors_where_they_are(self):
        p = self.flat_plan([{'kind': 'sdh', 'side': 90, 'distance': 0.2, 'depth': 0.14, 'size': 0.0625}])
        hole = lambda scene: next(s for s in scene.shapes if s.get('fill') == 'reflector_fill')
        x1 = sum(x for x, _ in hole(scan_plan.build_scene(p, 1, analysis=True))['points']) / 32
        x2 = sum(x for x, _ in hole(scan_plan.build_scene(p, 2, analysis=True))['points']) / 32
        self.assertAlmostEqual(x1, -0.2)
        self.assertAlmostEqual(x2, 0.2)     # flipped back by the drawing: still on the 90 side

    def test_printed_only_when_asked(self):
        items = [{'kind': 'sdh', 'side': 90, 'distance': 0.1, 'depth': 0.14, 'size': 0.0625}]
        quiet, printed = self.flat_plan(items), self.flat_plan(items, print_reflectors=True)
        has = lambda scene: any(s.get('group') == 'reflector' for s in scene.shapes)
        self.assertFalse(has(scan_plan.build_scene(quiet)))
        self.assertTrue(has(scan_plan.build_scene(printed)))

    def test_form_saves_reflectors_and_rejects_bad_ones(self):
        import json
        good = json.dumps([{'kind': 'sdh', 'side': 90, 'distance': 0.1, 'depth': 0.14, 'size': 0.0625}])
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'reflectors': good})
        self.assertEqual(ScanPlan.objects.get().reflectors[0]['label'], 'SDH 1')
        bad = json.dumps([{'kind': 'sdh', 'side': 90, 'distance': 0.1, 'depth': 0.9, 'size': 0.0625}])
        resp = self.client.get(reverse('scan-plan-scenes'), {**PLAN_FIELDS, 'reflectors': bad})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('past the wall', resp.json()['fields']['reflectors']['errors'][0])
