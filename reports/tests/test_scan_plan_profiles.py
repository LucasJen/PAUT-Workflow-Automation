"""Scan plans: weld profiles (double V, single bevel, J / U groove, compound bevel) and counterbores."""
import math

from django.test import TestCase
from django.urls import reverse

from reports.models import ScanPlan
from reports.services import scan_plan

from .test_scan_plans import PLAN_FIELDS


def plan(**fields):
    values = dict(thickness=1.0, bevel_angle=37.5, root_gap=0.125, root_face=0.0625, cap_width=None,
                  index_offset=None, exit_point=0.45, wedge_angle=36, angle_start=40, angle_stop=70, legs=2,
                  skew_90=True, skew_270=True)
    values.update(fields)
    return ScanPlan(**values)


def tan(degrees):
    return math.tan(math.radians(degrees))


class ProfileTests(TestCase):
    def test_single_v_is_unchanged(self):
        left, right = scan_plan.weld_faces(plan())
        self.assertEqual(left, scan_plan.weld_outline(plan()))
        self.assertAlmostEqual(left[0][0], -(0.0625 + (1 - 0.0625) * tan(37.5)))
        self.assertTrue(scan_plan.symmetric(plan()))

    def test_double_v_lands_in_the_middle_unless_placed(self):
        left, _ = scan_plan.weld_faces(plan(weld_type='double_v', bottom_bevel_angle=30))
        (top_x, _), (_, land_top), (_, land_bottom), (bottom_x, bottom_y) = left
        self.assertAlmostEqual(land_top, (1 - 0.0625) / 2)
        self.assertAlmostEqual(land_bottom - land_top, 0.0625)
        self.assertAlmostEqual(bottom_x, -(0.0625 + (1 - land_bottom) * tan(30)))
        self.assertEqual(bottom_y, 1.0)
        placed, _ = scan_plan.weld_faces(plan(weld_type='double_v', land_depth=0.25))
        self.assertAlmostEqual(placed[1][1], 0.25)

    def test_single_bevel_is_square_on_the_other_side(self):
        left, right = scan_plan.weld_faces(plan(weld_type='single_bevel', bevel_side=270))
        self.assertEqual([x for x, _ in left], [-0.0625, -0.0625])        # square on the 90 side
        self.assertAlmostEqual(right[0][0], 0.0625 + (1 - 0.0625) * tan(37.5))
        self.assertFalse(scan_plan.symmetric(plan(weld_type='single_bevel')))
        # The cap is centred on the opening: the toe is on the bevelled side
        cap_left, cap_right = scan_plan.cap_edges(plan(weld_type='single_bevel', bevel_side=270))
        self.assertAlmostEqual(scan_plan.toe(plan(weld_type='single_bevel', bevel_side=270)), cap_right)
        self.assertLess(-cap_left, cap_right)
        flipped, _ = scan_plan.weld_faces(plan(weld_type='single_bevel', bevel_side=90))
        self.assertLess(flipped[0][0], -0.5)

    def test_compound_bevel_changes_angle_at_its_height(self):
        left, _ = scan_plan.weld_faces(plan(weld_type='compound', thickness=1.5, transition_height=0.75,
                                            upper_bevel_angle=10))
        top, change, land_top, root = left
        self.assertAlmostEqual(land_top[1], 1.5 - 0.0625)
        self.assertAlmostEqual(change[1], 1.5 - 0.0625 - 0.75)
        self.assertAlmostEqual(change[0], -(0.0625 + 0.75 * tan(37.5)))
        self.assertAlmostEqual(top[0], change[0] - change[1] * tan(10))

    def test_u_groove_radius_runs_level_from_the_land_into_the_side_wall(self):
        p = plan(weld_type='u_groove', bevel_angle=15, root_radius=0.25)
        left, right = scan_plan.weld_faces(p)
        self.assertTrue(scan_plan.symmetric(p))
        land_top = left[-2]
        self.assertAlmostEqual(land_top[1], 1 - 0.0625)
        self.assertAlmostEqual(land_top[0], -0.0625)
        # Arc end: where the side wall (15 deg) is tangent to the radius
        phi = math.radians(90 - 15)
        end = left[1]
        self.assertAlmostEqual(end[0], -0.0625 - 0.25 * math.sin(phi))
        self.assertAlmostEqual(end[1], 1 - 0.0625 - 0.25 + 0.25 * math.cos(phi))
        self.assertAlmostEqual(left[0][0], end[0] - end[1] * tan(15))

    def test_j_bevel_is_one_sided(self):
        left, right = scan_plan.weld_faces(plan(weld_type='j_bevel', bevel_side=90, bevel_angle=15))
        self.assertGreater(len(left), 3)
        self.assertEqual(len(right), 2)

    def test_coverage_follows_the_profile(self):
        region = scan_plan.inspection_region(plan(weld_type='single_bevel', bevel_side=270, haz_width=0.25))
        self.assertAlmostEqual(region[0][0], -0.0625 - 0.25)        # the square side, out by the HAZ
        self.assertGreater(region[-1][0], 0.7)                       # the bevelled side's cap edge + HAZ


class CounterboreTests(TestCase):
    def test_back_wall_steps_up_to_the_bore(self):
        p = plan(thickness=0.5, counterbore_depth=0.1, counterbore_length=1.0, counterbore_taper=30)
        wall = scan_plan.back_wall(p, -3, 3)
        run = 0.1 / tan(30)
        self.assertEqual(wall[0], (-3, 0.5))
        self.assertAlmostEqual(wall[1][0], -1 - run)
        self.assertEqual(wall[2], (-1.0, 0.4))
        self.assertEqual(wall[3], (1.0, 0.4))
        self.assertEqual(scan_plan.back_wall(plan(thickness=0.5), -3, 3), [(-3, 0.5), (3, 0.5)])

    def test_weld_sits_on_the_counterbored_wall(self):
        p = plan(thickness=0.5, counterbore_depth=0.1)
        self.assertAlmostEqual(scan_plan.weld_thickness(p), 0.4)
        self.assertAlmostEqual(scan_plan.weld_outline(p)[-1][1], 0.4)

    def test_beams_skip_off_the_bore_near_the_weld_and_the_wall_beyond(self):
        p = plan(thickness=0.5, counterbore_depth=0.1, counterbore_length=1.0)
        near = scan_plan.trace(scan_plan.part(p), (-0.2, 0.0), 0, 1)
        self.assertEqual(near.surfaces, ['counterbore'])
        self.assertAlmostEqual(near.points[1][1], 0.4)
        far = scan_plan.trace(scan_plan.part(p), (-2.0, 0.0), 0, 1)
        self.assertEqual(far.surfaces, ['back wall'])
        self.assertAlmostEqual(far.points[1][1], 0.5)

    def test_drawing_and_coverage_with_a_counterbore(self):
        p = plan(thickness=0.5, counterbore_depth=0.1, index_offset=0.6, angle_start=45, angle_stop=70)
        scene = scan_plan.build_scene(p, analysis=True)
        self.assertTrue(scan_plan.render_scene(scene).startswith(b'\x89PNG'))
        self.assertGreater(scan_plan.coverage(p).fraction, 0.5)


class AsymmetricDrawingTests(TestCase):
    def test_mirrored_drawing_turns_an_asymmetric_weld_round(self):
        p = plan(weld_type='single_bevel', bevel_side=270, index_offset=1.0)
        weld = lambda scene: next(s for s in scene.shapes if s['kind'] == 'polygon' and s.get('fill') == 'weld')
        side_1, side_2 = weld(scan_plan.build_scene(p, 1)), weld(scan_plan.build_scene(p, 2))
        # The 270 drawing is flipped when shown, so its weld is the real one turned round
        self.assertEqual(sorted((round(-x, 9), round(y, 9)) for x, y in side_2['points']),
                         sorted((round(x, 9), round(y, 9)) for x, y in side_1['points']))


class FormTests(TestCase):
    def test_saves_a_double_v_with_a_counterbore(self):
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'weld_type': 'double_v', 'land_depth': '0.1',
                                                     'counterbore_depth': '0.05', 'counterbore_length': '0.75'})
        saved = ScanPlan.objects.get()
        self.assertEqual(saved.weld_type, 'double_v')
        self.assertEqual((saved.land_depth, saved.counterbore_depth, saved.counterbore_taper), (0.1, 0.05, 30.0))

    def test_counterbore_must_leave_wall(self):
        resp = self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'counterbore_depth': '0.28'})
        self.assertContains(resp, 'The counterbore must leave some wall')
        self.assertFalse(ScanPlan.objects.exists())

    def test_metric_profile_lengths_are_stored_in_inches(self):
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'units': 'metric', 'thickness': '25.4',
                                                     'index_offset': '12.7', 'weld_type': 'u_groove',
                                                     'root_radius': '6.35', 'counterbore_depth': '2.54'})
        saved = ScanPlan.objects.get()
        self.assertAlmostEqual(saved.root_radius, 0.25)
        self.assertAlmostEqual(saved.counterbore_depth, 0.1)

    def test_editor_lists_which_types_use_which_fields(self):
        page = self.client.get(reverse('new-scan-plan')).content.decode()
        self.assertIn('data-shows-fields', page)
        self.assertIn('name="counterbore_depth"', page)


class FillMarkTests(TestCase):
    def test_required_fields_are_red_and_setup_values_yellow(self):
        from reports.forms import ScanPlanForm
        form = ScanPlanForm()
        fill = {name: field.widget.attrs.get('data-fill') for name, field in form.fields.items()}
        self.assertEqual(fill['name'], 'user')
        self.assertEqual(fill['bevel_angle'], 'user')              # needed to draw
        self.assertEqual(fill['thickness'], 'auto')                # from the sensitivity block
        self.assertEqual((fill['probe_model'], fill['wedge_model']), ('auto', 'auto'))
        self.assertIsNone(fill['index_offset'])                    # blank has a meaning: the weld toe
        self.assertIsNone(fill['weld_type'])                       # has a default when not posted
        page = self.client.get(reverse('new-scan-plan')).content.decode()
        self.assertIn('data-fill-marks', page)
        self.assertIn('id="fill-next"', page)

    def test_drawing_names_the_fields_it_needs(self):
        resp = self.client.get(reverse('scan-plan-scenes'), {**PLAN_FIELDS, 'thickness': '', 'bevel_angle': '95'})
        self.assertEqual(resp.status_code, 400)
        fields = resp.json()['fields']
        self.assertEqual(fields['thickness']['label'], 'Thickness')
        self.assertEqual(fields['thickness']['errors'], ['This field is required.'])
        self.assertIn('Enter an angle from 0 to 89°.', fields['bevel_angle']['errors'])


class NewPlanStartTests(TestCase):
    def test_new_plan_opens_with_one_drawing_of_a_half_inch_plate(self):
        page = self.client.get(reverse('new-scan-plan'))
        form = page.context['form']
        self.assertEqual(form['thickness'].value(), 0.5)
        self.assertEqual((form['skew_90'].value(), form['skew_270'].value()), (True, False))
        self.assertEqual((form['bevel_angle'].value(), form['beam_direction'].value()), (37.5, 'axial'))
        # What the page sends for its first drawing draws exactly one
        values = {name: form[name].value() for name in ('thickness', 'bevel_angle', 'root_gap', 'root_face',
                                                        'exit_point', 'wedge_angle', 'angle_start', 'angle_stop',
                                                        'angle_step', 'legs', 'shear_velocity', 'first_element')}
        data = self.client.get(reverse('scan-plan-scenes'), {**values, 'skew_90': 'on'}).json()
        self.assertEqual(len(data['drawings']), 1)
        self.assertEqual(data['drawings'][0]['meta']['thickness'], 0.5)
