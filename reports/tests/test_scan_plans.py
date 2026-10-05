"""Scan plans: geometry, drawing, the scan plan pages, and the weld report's Scan Plan page."""
import io
import math

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from equipment.compat import BEAMTOOL_SOURCE
from equipment.models import ProbeModel, SensitivityBlock, WedgeModel
from reports.models import Report, ReportGroup, ReportProbe, ScanPlan, Setup
from reports.services import scan_plan
from reports.services.excel_report import weld_pages

PLAN_FIELDS = {
    'name': '6in Sch 40', 'pipe_size': '6in Sch 40', 'skew_90': 'on', 'skew_270': 'on', 'legs': '2',
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


class TracerTests(TestCase):
    def test_flat_plate_trace_names_the_surfaces_and_sound_path(self):
        plan = ScanPlan(thickness=0.5, legs=2)
        beam = scan_plan.trace(scan_plan.part(plan), (0.0, 0.0), 45, 2)
        self.assertEqual(beam.surfaces, ['back wall', 'scanning surface'])
        self.assertAlmostEqual(beam.sound_path, 2 * 0.5 * math.sqrt(2))

    def test_reflects_off_any_surface(self):
        # A 45 deg beam meets an end wall, comes back to the back wall, then the scanning surface
        Surface = scan_plan.geometry.Surface
        block = scan_plan.geometry.Part([
            Surface((-5.0, 0.0), (0.5, 0.0), 'top'), Surface((-5.0, 1.0), (0.5, 1.0), 'bottom'),
            Surface((0.5, 0.0), (0.5, 1.0), 'end')], 1.0)
        beam = scan_plan.trace(block, (0.0, 0.0), 45, 3)
        self.assertEqual(beam.surfaces, ['end', 'bottom', 'top'])
        for (x, y), (ex, ey) in zip(beam.points, [(0, 0), (0.5, 0.5), (0, 1), (-1, 0)]):
            self.assertAlmostEqual(x, ex)
            self.assertAlmostEqual(y, ey)

    def test_stops_when_the_beam_leaves_the_part(self):
        short = scan_plan.geometry.Part([scan_plan.geometry.Surface((0.5, 1.0), (1.0, 1.0), 'ledge')], 1.0)
        self.assertEqual(scan_plan.trace(short, (0.0, 0.0), 0, 2).points, [(0.0, 0.0)])


class SceneTests(TestCase):
    def test_scene_is_plain_data_with_beam_readouts(self):
        import json
        plan = make_plan(angle_start=45, angle_stop=60, angle_step=5)
        scene = scan_plan.build_scene(plan, side=2)
        self.assertTrue(scene.mirror)
        beams = [s for s in scene.shapes if s.get('data', {}).get('angle') is not None]
        self.assertEqual([b['data']['angle'] for b in beams], [45, 50, 55, 60])
        self.assertEqual(beams[0]['data']['surfaces'], ['back wall', 'scanning surface'])
        json.dumps(scene.as_dict())   # sendable to the browser as it is

    def test_render_scene_matches_render_png(self):
        plan = make_plan()
        self.assertEqual(scan_plan.render_scene(scan_plan.build_scene(plan)), scan_plan.render_png(plan))


class CoverageTests(TestCase):
    def plan(self, **fields):
        values = dict(thickness=0.5, bevel_angle=30, root_gap=0.0625, root_face=0.0625, cap_width=None,
                      exit_point=0.45, wedge_angle=36, angle_start=40, angle_stop=70, angle_step=1, legs=2,
                      skew_90=True, skew_270=True, index_offset_2=None, skew_90_2=False, skew_270_2=False)
        values.update(fields)
        return ScanPlan(**values)

    def test_inspection_volume_is_the_weld_plus_haz(self):
        plan = self.plan(haz_width=0.25)
        region = scan_plan.inspection_region(plan)
        self.assertAlmostEqual(region[0][0], scan_plan.weld_outline(plan)[0][0] - 0.25)
        self.assertAlmostEqual(region[-1][0], -region[0][0])

    def test_coverage_falls_off_with_the_probe_too_far_back(self):
        near = scan_plan.coverage(self.plan(index_offset=0.6))
        far = scan_plan.coverage(self.plan(index_offset=4.0))
        self.assertTrue(near.full)
        self.assertEqual(far.fraction, 0.0)
        self.assertEqual(set(near.by_drawing), {(1, 1), (1, 2)})

    def test_one_skew_alone_covers_less_than_both(self):
        both = scan_plan.coverage(self.plan(index_offset=0.6))
        one = scan_plan.coverage(self.plan(index_offset=0.6, skew_270=False))
        self.assertLess(one.fraction, both.fraction)

    def test_suggested_offset_covers_the_volume(self):
        plan = self.plan()
        suggestion = scan_plan.suggest_offset(plan)
        self.assertEqual(suggestion.fraction, 1.0)
        self.assertIsNone(suggestion.second_offset)
        self.assertLessEqual(suggestion.low, suggestion.offset)
        self.assertLessEqual(suggestion.offset, suggestion.high)
        self.assertGreaterEqual(suggestion.low, scan_plan.cap_width(plan) / 2)   # wedge not on the cap
        plan.index_offset = suggestion.offset
        self.assertTrue(scan_plan.coverage(plan).full)

    def test_suggests_a_second_offset_when_one_cannot_cover(self):
        plan = self.plan(thickness=1.5, angle_start=60, angle_stop=70, legs=1, skew_270=False)
        suggestion = scan_plan.suggest_offset(plan)
        self.assertLess(suggestion.fraction, 1.0)
        self.assertIsNotNone(suggestion.second_offset)
        self.assertGreater(suggestion.pair_fraction, suggestion.fraction)


class SimpleModeTests(TestCase):
    def test_a_form_without_mode_or_haz_saves_as_simple_with_the_default_haz(self):
        self.client.post(reverse('new-scan-plan'), PLAN_FIELDS)
        plan = ScanPlan.objects.get()
        self.assertEqual((plan.mode, plan.haz_width), ('simple', 0.25))

    def test_metric_haz_is_stored_in_inches(self):
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'units': 'metric', 'thickness': '7.11',
                                                     'index_offset': '12.2', 'haz_width': '12.7', 'mode': 'advanced'})
        plan = ScanPlan.objects.get()
        self.assertEqual(plan.mode, 'advanced')
        self.assertAlmostEqual(plan.haz_width, 0.5)

    def test_editor_marks_the_advanced_fields(self):
        page = self.client.get(reverse('new-scan-plan')).content.decode()
        self.assertIn('id="advanced-fields"', page)
        self.assertIn('name="mode"', page)

    def test_wedge_data_reports_coverage(self):
        data = self.client.get(reverse('scan-plan-wedge-data'), PLAN_FIELDS).json()['coverage']
        self.assertEqual([(d['position'], d['side']) for d in data['drawings']], [(1, 1), (1, 2)])
        self.assertGreater(data['fraction'], 0)

    def test_suggest_endpoint(self):
        data = self.client.get(reverse('scan-plan-suggest'), PLAN_FIELDS).json()
        self.assertEqual(data['fraction'], 1.0)
        self.assertLessEqual(data['low'], data['offset'])
        self.assertGreaterEqual(data['low'], data['toe'])
        self.assertEqual(self.client.get(reverse('scan-plan-suggest'), {'thickness': ''}).status_code, 400)

    def test_preview_shades_gaps_but_the_printed_drawing_does_not(self):
        plan = make_plan(index_offset=3.0)   # too far back to cover the weld
        printed = scan_plan.build_scene(plan)
        live = scan_plan.build_scene(plan, analysis=True)
        self.assertFalse([s for s in printed.shapes if s.get('fill') == 'gap'])
        self.assertTrue([s for s in live.shapes if s.get('fill') == 'gap'])
        self.assertEqual(self.client.get(reverse('scan-plan-preview'), PLAN_FIELDS)['Content-Type'], 'image/png')


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
        # No thickness: that comes from the report's sensitivity block (a saved setup has none)
        self.assertEqual(list(values.values())[0]['fields'],
                         {'cap_width': '', 'angle_start': 42.0, 'angle_stop': 73.0, 'angle_step': 1.0})
        self.assertIsNone(list(values.values())[0]['block'])
        # the wedge angle comes only from the wedge selector

    def test_fill_from_a_report_setup_takes_the_reports_sensitivity_block(self):
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        report = Report.objects.create(sensitivity_block=block)
        setup = Setup.objects.create(report=report, title='PAUT 1', specimen_thickness='9.9', weld_bevel_angle='30')
        item = self.client.get(reverse('new-scan-plan')).context['setup_fill_values'][setup.pk]
        fields = item['fields']
        self.assertEqual(fields['sensitivity_block'], block.pk)
        self.assertEqual(fields['thickness'], scan_plan.first_number(block.test_thickness)
                         or scan_plan.first_number(block.cal_thickness))   # never the setup's 9.9
        self.assertEqual(fields['bevel_angle'], 30.0)    # the setup's own weld (from its .nde) wins
        self.assertEqual((item['name'], item['block']), ('PAUT 1', str(block)))

    def test_fill_from_a_weld_group_takes_the_reports_sensitivity_block(self):
        block = SensitivityBlock.objects.get(pipe_size='6in Sch 40')
        report = Report.objects.create(report_type='paut_weld', sensitivity_block=block, document_filename='W5')
        probe = ReportProbe.objects.create(report=report, order=0, kind='paut', model='10L32-A1')
        group = ReportGroup.objects.create(report=report, order=0, probe=probe, angles='40°-70°')  # dash = range
        item = self.client.get(reverse('new-scan-plan')).context['group_fill_values'][f'g{group.pk}']
        self.assertEqual(item['fields']['sensitivity_block'], block.pk)
        self.assertIn('thickness', item['fields'])
        self.assertEqual((item['fields']['angle_start'], item['fields']['angle_stop']), (40.0, 70.0))
        self.assertEqual(item['name'], 'W5')

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
        self.assertEqual(values['wedge_model'][wedge.pk], {'wedge_angle': 38.9, 'wedge_primary_offset': '', 'wedge_first_element_height': '', 'wedge_velocity': '', 'wedge_length': '', 'wedge_height': ''})


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
        self.assertEqual(sections['Probe positions'],
                         ['index_offset', 'skew_90', 'skew_270', 'index_offset_2', 'skew_90_2', 'skew_270_2'])
        self.assertIn('units', sections['Scan plan'])
        self.assertEqual(sections['Beams'], ['angle_start', 'angle_stop', 'legs', 'angle_step'])
        hidden = {f.name for f in form.hidden_fields()}
        self.assertEqual(hidden, {'wedge_angle', 'exit_point', 'wedge_primary_offset', 'wedge_first_element_height',
                                  'wedge_velocity', 'wedge_length', 'wedge_height'})
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
        self.assertEqual(values, {'wedge_angle': 39.0, 'exit_point': expected, 'wedge_primary_offset': '', 'wedge_first_element_height': '', 'wedge_velocity': '', 'wedge_length': '', 'wedge_height': ''})


class OffsetAndPreviewTests(TestCase):
    def test_preview_draws_before_a_name_or_offset_is_entered(self):
        resp = self.client.get(reverse('scan-plan-preview'), {**PLAN_FIELDS, 'name': '', 'index_offset': ''})
        self.assertEqual(resp['Content-Type'], 'image/png')

    def test_name_still_needed_to_save(self):
        resp = self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'name': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ScanPlan.objects.exists())

    def test_blank_offset_puts_the_wedge_at_the_weld_toe(self):
        plan = make_plan(index_offset=None, cap_width=0.5)
        self.assertEqual(scan_plan.index_offset(plan), 0.25)
        self.assertEqual(max(x for x, _ in scan_plan.layout(plan).wedge), -0.25)  # wedge front at the toe
        plan.index_offset = 0.48
        self.assertEqual(scan_plan.index_offset(plan), 0.48)
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'index_offset': ''})
        self.assertIsNone(ScanPlan.objects.get(name=PLAN_FIELDS['name']).index_offset)

    def test_setup_offset_fills_the_scan_plan(self):
        setup = Setup.objects.create(title='PAUT 1', specimen_thickness='0.280', index_offset='0.350')
        values = self.client.get(reverse('new-scan-plan')).context['setup_fill_values']
        self.assertEqual(values[setup.pk]['fields']['index_offset'], 0.35)


class NdeIndexOffsetTests(TestCase):
    def test_wedge_position_gives_the_index_offset(self):
        from reports.services.nde_parser import extract_groups
        setup = {
            'probes': [{'id': 0, 'model': '10L32-A1', 'wedgeAssociation': {'wedgeId': 0, 'mountingLocationId': 0}}],
            'wedges': [{'id': 0, 'model': 'SA1-N60S 10L32', 'positioning': {'vCoordinateOffset': -0.00889}}],
            'groups': [{'id': 0, 'processes': [{'ultrasonicPhasedArray': {'pulseEcho': {'probeId': 0}}}]}],
        }
        values = extract_groups(setup)[0]['values']
        self.assertEqual((values['imperial']['index_offset'], values['metric']['index_offset']), ('0.350', '8.89'))


WELD_SETUP = {
    'probes': [{'id': 0, 'model': '10L32-A1', 'wedgeAssociation': {'wedgeId': 0, 'mountingLocationId': 0}}],
    'wedges': [{'id': 0, 'model': 'SA1-N60S 10L32', 'positioning': {'vCoordinateOffset': -0.00889}}],
    'specimens': [{'id': 0, 'plateGeometry': {'thickness': 0.00762}, 'weldGeometry': {
        'bevelShape': 'V', 'offset': 0.0015875, 'upperCap': {'width': 0.0127, 'height': 0.002},
        'fills': [{'angle': 37.5, 'height': 0.0056}], 'land': {'height': 0.0015875}}}],
    'dataMappings': [{'id': 0, 'specimenId': 0}],
    'groups': [{'id': 0, 'processes': [{'ultrasonicPhasedArray': {'pulseEcho': {'probeId': 0}}, 'dataMappingId': 0}]}],
}


class UnitsTests(TestCase):
    def test_nde_import_gives_units_and_weld_data(self):
        from reports.services.nde_parser import extract_groups
        values = extract_groups(WELD_SETUP)[0]['values']
        imperial, metric = values['imperial'], values['metric']
        self.assertEqual((imperial['units'], metric['units']), ('imperial', 'metric'))
        self.assertEqual(imperial['weld_bevel_angle'], '37.5')
        self.assertEqual((imperial['weld_root_face'], imperial['weld_root_gap']), ('0.062', '0.125'))
        self.assertEqual(metric['weld_root_gap'], '3.17')
        self.assertNotIn('weld_cap_width', imperial)  # OmniScan's default cap; the scan plan calculates it
        self.assertEqual(imperial['specimen_thickness'], '0.300')

    def test_fill_from_a_metric_setup_is_in_inches(self):
        setup = Setup.objects.create(units='metric', specimen_thickness='7.62', index_offset='8.89',
                                     weld_bevel_angle='37.5', weld_root_face='1.59', weld_root_gap='3.18',
                                     weld_cap_width='12.7')
        fill = self.client.get(reverse('new-scan-plan')).context['setup_fill_values'][setup.pk]['fields']
        self.assertNotIn('thickness', fill)   # from a sensitivity block only
        self.assertEqual((fill['index_offset'], fill['bevel_angle']), (0.35, 37.5))
        self.assertEqual((fill['root_face'], fill['root_gap'], fill['cap_width']), (0.0626, 0.1252, 0.5))

    def test_metric_scan_plan_is_entered_in_mm_and_stored_in_inches(self):
        resp = self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'units': 'metric', 'thickness': '7.112',
                                                           'index_offset': '12.192', 'shear_velocity': '3241'})
        plan = ScanPlan.objects.get()
        self.assertRedirects(resp, reverse('edit-scan-plan', args=[plan.pk]))
        self.assertAlmostEqual(plan.thickness, 0.28)
        self.assertAlmostEqual(plan.index_offset, 0.48)
        self.assertAlmostEqual(plan.shear_velocity, 0.1276, places=4)
        self.assertEqual(plan.thickness_text, '7.11 mm')
        form = self.client.get(reverse('edit-scan-plan', args=[plan.pk])).context['form']
        self.assertEqual((form['thickness'].initial, form['index_offset'].initial), (7.11, 12.19))

    def test_fill_leaves_cap_width_blank_to_be_calculated(self):
        setup = Setup.objects.create(specimen_thickness='0.280', weld_bevel_angle='37.5')
        fill = self.client.get(reverse('new-scan-plan')).context['setup_fill_values'][setup.pk]['fields']
        self.assertEqual(fill['cap_width'], '')

    def test_scan_plan_without_units_stays_imperial(self):
        data = {k: v for k, v in PLAN_FIELDS.items() if k != 'units'}
        self.client.post(reverse('new-scan-plan'), data)
        self.assertEqual(ScanPlan.objects.get().units, 'imperial')

    def test_metric_setup_prints_mm_in_reports(self):
        from reports.services.report_render import length_unit, velocity_unit
        self.assertEqual((length_unit(Setup(units='metric')), velocity_unit(Setup(units='metric'))), (' mm', ' m/s'))
        self.assertEqual((length_unit(Setup()), velocity_unit(Setup())), ('"', ' in/µs'))


class FileGeometryTests(TestCase):
    """The wedge geometry a setup's .nde recorded draws the scan plan; the catalogue gives the size."""

    def standard_and_short(self):
        standard = WedgeModel.objects.create(model='SA1-N60S 10L32', probe_series='A1', probe_fit='10L32',
                                             wedge_angle=39.0, velocity=2330.0, primary_offset=-27.19,
                                             first_element_height=5.15, length=30.38, height=16.41)
        short = WedgeModel.objects.create(model='SA1-N60S-IHC-SA 10L32', probe_series='A1', probe_fit='10L32',
                                          wedge_angle=38.52, velocity=2330.0, primary_offset=-21.19,
                                          first_element_height=8.94, length=23.62, height=19.17)
        return standard, short

    def test_file_geometry_replaces_the_catalogues(self):
        standard, _ = self.standard_and_short()
        plan = make_plan(probe_model=ProbeModel.objects.get(model='10L32-A1'), wedge_model=standard,
                         first_element=1, aperture_elements=27, wedge_angle=38.9,
                         wedge_primary_offset=-21.361, wedge_first_element_height=8.382, wedge_velocity=2330.0)
        lay = scan_plan.layout(plan)
        self.assertTrue(lay.from_file)
        self.assertTrue(lay.exact)
        s = 13 * 0.31 / 25.4
        a = math.radians(38.9)
        self.assertAlmostEqual(lay.source[0], -0.48 - 21.361 / 25.4 + s * math.cos(a))
        self.assertAlmostEqual(-lay.source[1], 8.382 / 25.4 + s * math.sin(a))
        # size from the catalogue: 30.38 mm long, and a low heel (about 1.1 mm)
        back = min(x for x, _ in lay.wedge)
        self.assertAlmostEqual((max(x for x, _ in lay.wedge) - back) * 25.4, 30.38)
        heel = max(-y for x, y in lay.wedge if abs(x - back) < 1e-9) * 25.4
        self.assertAlmostEqual(heel, 1.1, delta=0.2)

    def test_probe_is_a_thin_untrimmed_element_block(self):
        for wedge in self.standard_and_short():
            with self.subTest(wedge=wedge.model):
                plan = make_plan(probe_model=ProbeModel.objects.get(model='10L32-A1'), wedge_model=wedge,
                                 first_element=6, aperture_elements=27)
                lay = scan_plan.layout(plan)
                self.assertEqual(len(lay.probe), 4)  # whole block, not cut at the wedge's back
                self.assertAlmostEqual(math.dist(lay.probe[0], lay.probe[1]) * 25.4, 32 * 0.31 + 2)
                self.assertAlmostEqual(math.dist(lay.probe[1], lay.probe[2]) * 25.4, 2.0)

    def test_setup_fill_carries_the_file_geometry(self):
        setup = Setup.objects.create(specimen_thickness='0.280', wedge_angle='38.9', wedge_primary_offset=-21.361,
                                     wedge_first_element_height=8.382, wedge_velocity=2330.0)
        item = self.client.get(reverse('new-scan-plan')).context['setup_fill_values'][setup.pk]
        self.assertEqual(item['wedge_geometry'], {'wedge_primary_offset': -21.361, 'wedge_first_element_height': 8.382,
                                                  'wedge_velocity': 2330.0, 'wedge_angle': 38.9})
        setup.wedge_length, setup.wedge_height = 23.597, 18.771
        setup.save()
        item = self.client.get(reverse('new-scan-plan')).context['setup_fill_values'][setup.pk]
        self.assertEqual((item['wedge_geometry']['wedge_length'], item['wedge_geometry']['wedge_height']),
                         (23.597, 18.771))

    def test_nde_import_records_the_wedge_geometry(self):
        from reports.services.nde_parser import extract_groups
        setup = {**WELD_SETUP, 'wedges': [{'id': 0, 'model': 'SA1-N60S 10L32', 'angleBeamWedge': {
            'longitudinalVelocity': 2330.0, 'mountingLocations': [
                {'id': 0, 'wedgeAngle': 38.9, 'primaryOffset': -0.021361, 'tertiaryOffset': 0.008382}]}}]}
        for values in extract_groups(setup)[0]['values'].values():
            self.assertEqual((values['wedge_primary_offset'], values['wedge_first_element_height'],
                              values['wedge_velocity']), ('-21.361', '8.382', '2330.0'))


class FileWedgeSizeTests(TestCase):
    def test_the_files_wedge_size_is_drawn(self):
        """PPI 31-37575: the file's 'SA1-N60S 10L32' is 23.6 x 18.8 mm, the short wedge."""
        standard = WedgeModel.objects.create(model='SA1-N60S 10L32', probe_series='A1', probe_fit='10L32',
                                             wedge_angle=39.0, velocity=2330.0, primary_offset=-27.19,
                                             first_element_height=5.15, length=30.38, height=16.41)
        plan = make_plan(probe_model=ProbeModel.objects.get(model='10L32-A1'), wedge_model=standard,
                         first_element=1, aperture_elements=27, wedge_angle=38.9, wedge_primary_offset=-21.361,
                         wedge_first_element_height=8.382, wedge_velocity=2330.0, wedge_length=23.597,
                         wedge_height=18.771)
        lay = scan_plan.layout(plan)
        xs = [x for x, _ in lay.wedge]
        self.assertAlmostEqual((max(xs) - min(xs)) * 25.4, 23.597)
        self.assertAlmostEqual(max(-y for _, y in lay.wedge) * 25.4, 18.771)
        data = lay.wedge_data
        self.assertEqual(data['source'], '.nde file')
        self.assertAlmostEqual(data['length'], 23.597)
        self.assertAlmostEqual(data['first_element_behind_front'], 21.361)
        self.assertAlmostEqual(data['first_element_height'], 8.382)
        # face height at the back: 8.382 - (23.597 - 21.361) * tan(38.9 deg)
        self.assertAlmostEqual(data['heel_height'], 8.382 - (23.597 - 21.361) * math.tan(math.radians(38.9)))

    def test_wedge_data_endpoint(self):
        WedgeModel.objects.create(model='SA1-N60S 10L32', probe_series='A1', probe_fit='10L32', wedge_angle=39.0,
                                  velocity=2330.0, primary_offset=-27.19, first_element_height=5.15,
                                  length=30.38, height=16.41)
        probe = ProbeModel.objects.get(model='10L32-A1')
        wedge = WedgeModel.objects.get(model='SA1-N60S 10L32')
        resp = self.client.get(reverse('scan-plan-wedge-data'),
                               {**PLAN_FIELDS, 'probe_model': probe.pk, 'wedge_model': wedge.pk})
        data = resp.json()['wedge']
        self.assertEqual(data['source'], 'catalogue')
        self.assertAlmostEqual(data['length'], 30.38)
        self.assertIsNone(self.client.get(reverse('scan-plan-wedge-data'), PLAN_FIELDS).json()['wedge'])
        self.assertEqual(self.client.get(reverse('scan-plan-wedge-data'), {**PLAN_FIELDS, 'thickness': ''}).status_code, 400)


class SkewTests(TestCase):
    def test_one_to_four_drawings(self):
        plan = make_plan()
        self.assertEqual(plan.drawings, [(1, 0.48, 90), (1, 0.48, 270)])
        plan.skew_270 = False
        self.assertEqual(plan.drawings, [(1, 0.48, 90)])
        plan.skew_270 = True
        plan.index_offset_2, plan.skew_90_2, plan.skew_270_2 = 0.75, True, True
        self.assertEqual(plan.drawings, [(1, 0.48, 90), (1, 0.48, 270), (2, 0.75, 90), (2, 0.75, 270)])

    def test_at_least_one_skew_and_second_offset_needs_a_value(self):
        fields = {k: v for k, v in PLAN_FIELDS.items() if k not in ('skew_90', 'skew_270')}
        resp = self.client.post(reverse('new-scan-plan'), fields)
        self.assertContains(resp, 'Tick at least one skew to draw.')
        resp = self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'skew_90_2': 'on'})
        self.assertContains(resp, 'Enter the second index offset, or untick its skews.')
        self.assertFalse(ScanPlan.objects.exists())
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'index_offset_2': '0.75', 'skew_270_2': 'on'})
        plan = ScanPlan.objects.get()
        self.assertEqual(plan.drawings[-1], (2, 0.75, 270))

    def test_second_position_draws_at_its_offset(self):
        plan = make_plan(index_offset=0.48, index_offset_2=0.75)
        second = scan_plan.at_position(plan, 2)
        self.assertEqual(scan_plan.index_offset(second), 0.75)
        self.assertEqual(plan.index_offset, 0.48)  # the plan itself is unchanged
        resp = self.client.get(reverse('scan-plan-preview'),
                               {**PLAN_FIELDS, 'index_offset_2': '0.75', 'skew_90_2': 'on', 'side': '2', 'position': '2'})
        self.assertEqual(resp['Content-Type'], 'image/png')

    def test_metric_second_offset_is_stored_in_inches(self):
        self.client.post(reverse('new-scan-plan'), {**PLAN_FIELDS, 'units': 'metric', 'thickness': '7.112',
                                                    'index_offset': '12.192', 'index_offset_2': '19.05',
                                                    'skew_90_2': 'on', 'shear_velocity': '3241'})
        self.assertAlmostEqual(ScanPlan.objects.get().index_offset_2, 0.75)


class ScanPlanFromWeldTests(TestCase):
    """The weld report's Results: a weld's Scan plan button adds it to the report's scan plan."""
    url = reverse('scan-plan-from-weld')

    def setUp(self):
        from reports.models import ReportGroup, ReportProbe
        self.report = Report.objects.create(report_type='paut_weld', document_filename='PPI-31-W5')
        ReportProbe.objects.create(report=self.report, order=0, kind='na')
        probe = ReportProbe.objects.create(report=self.report, order=1, kind='paut', model='10L32-A1',
                                           wedge_angle='36°', wedge_primary_offset=-20.0, wedge_first_element_height=8.0)
        ReportGroup.objects.create(report=self.report, order=0, not_applicable=True)
        ReportGroup.objects.create(report=self.report, order=1, probe=probe, angles='42.0° - 73.0°',
                                   angle_increment='1.0°', first_element=1, aperture_elements=16)

    def weld(self, **fields):
        data = {'report_id': self.report.pk, 'cl_offset': '0.475', 'weld_width': '0.8', 'probe1_location': '90/270',
                'probe1_thk': '0.280', **fields}
        return self.client.post(self.url, data).json()

    def plan(self):
        self.report.refresh_from_db()
        return self.report.scan_plan

    def test_first_weld_makes_and_links_the_plan(self):
        data = self.weld()
        plan = self.plan()
        self.assertTrue(data['ok'])
        self.assertEqual((plan.name, plan.thickness, plan.cap_width, plan.index_offset), ('PPI-31-W5', 0.28, 0.8, 0.475))
        self.assertEqual((plan.skew_90, plan.skew_270, plan.index_offset_2), (True, True, None))
        # probe / wedge / angles from the first PAUT group (not the N/A one)
        self.assertEqual((plan.angle_start, plan.angle_stop, plan.aperture_elements), (42.0, 73.0, 16))
        self.assertEqual((plan.wedge_primary_offset, plan.wedge_angle), (-20.0, 36.0))
        self.assertEqual(data['plan']['url'], reverse('edit-scan-plan', args=[plan.pk]))
        self.assertEqual(len(plan.drawings), 2)

    def test_same_offset_and_skews_add_nothing(self):
        self.weld()
        data = self.weld()
        self.assertIn('already in scan plan', data['message'])
        self.assertEqual(ScanPlan.objects.count(), 1)
        self.assertEqual(len(self.plan().drawings), 2)

    def test_same_offset_adds_only_the_missing_skew(self):
        self.weld(probe1_location='90')
        plan = self.plan()
        self.assertEqual((plan.skew_90, plan.skew_270), (True, False))
        data = self.weld(probe1_location='90/270')
        plan = self.plan()
        self.assertEqual((plan.skew_90, plan.skew_270), (True, True))
        self.assertIn('(270°)', data['message'])

    def test_new_offset_is_the_second_then_a_third_is_refused(self):
        self.weld()
        self.weld(cl_offset='0.600', probe1_location='270')
        plan = self.plan()
        self.assertEqual((plan.index_offset_2, plan.skew_90_2, plan.skew_270_2), (0.6, False, True))
        self.assertEqual(len(plan.drawings), 3)
        self.weld(cl_offset='0.600', probe1_location='90')     # same second offset: its other skew
        self.assertTrue(self.plan().skew_90_2)
        data = self.weld(cl_offset='0.750')
        self.assertFalse(data['ok'])
        self.assertIn('already has two offsets', data['message'])
        self.assertEqual(len(self.plan().drawings), 4)

    def test_thickness_difference_is_a_warning(self):
        self.weld()
        data = self.weld(probe1_thk='0.300')
        self.assertIn('Thickness 0.300" differs', data['message'])
        self.assertEqual(self.plan().thickness, 0.28)

    def test_unsaved_report_or_no_thickness(self):
        self.assertEqual(self.client.post(self.url, {'report_id': ''}).json()['message'], 'Save the report first.')
        self.assertFalse(self.weld(probe1_thk='')['ok'])
        self.assertIsNone(self.plan())
