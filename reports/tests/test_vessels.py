import io
import json

from django.test import TestCase
from django.urls import reverse
from PIL import Image

from reports.models import Vessel
from reports.services.vessel import (
    VesselSpec, alpha, build_scene, ends, format_diameter, format_length, parse_length, render_png, side_names,
)
from reports.services.vessel.layout import build_layout


def course(length, **extra):
    return {'kind': 'course', 'length': length, **extra}


class LengthTests(TestCase):
    def test_reads_lengths_as_the_client_drawings_write_them(self):
        for text, inches in [("14'-0\"", 168), ("14'", 168), ('66"', 66), ('66', 66), ("5'-6 1/2\"", 66.5),
                             ("7'-6\"", 90), ('1/2', 0.5), ('6-1/2', 6.5), ("126'-8\"", 1520), ('1676 mm', 1676 / 25.4)]:
            self.assertAlmostEqual(parse_length(text), inches, msg=text)

    def test_metric_takes_millimetres_unless_marked_in_inches(self):
        self.assertAlmostEqual(parse_length('1676', metric=True), 1676 / 25.4)
        self.assertAlmostEqual(parse_length('66"', metric=True), 66)
        self.assertIsNone(parse_length('  '))
        with self.assertRaises(ValueError):
            parse_length('six feet')

    def test_formats_feet_inches_for_lengths_and_inches_for_diameters(self):
        self.assertEqual(format_length(168), "14'-0\"")
        self.assertEqual(format_length(66.5), "5'-6 1/2\"")
        self.assertEqual(format_length(30), '30"')
        self.assertEqual(format_diameter(66), '66"')
        self.assertEqual(format_diameter(1676 / 25.4, metric=True), '1676 mm')


class DirectionTests(TestCase):
    def test_horizontal_vessel_seen_from_the_south(self):
        spec = VesselSpec('horizontal', view_from='S')
        self.assertEqual(ends(spec), ('W', 'E'))
        self.assertEqual(side_names(spec), ('S', 'N'))
        self.assertEqual(alpha(spec, 'Top'), 0)
        self.assertEqual(alpha(spec, 'S'), 90)      # towards the viewer
        self.assertEqual(alpha(spec, 'N'), 270)
        self.assertIsNone(alpha(spec, 'E'))         # along the axis: not a shell nozzle direction

    def test_tower_seen_from_the_south_has_east_on_the_right(self):
        spec = VesselSpec('vertical', view_from='S')
        self.assertEqual(alpha(spec, 'E'), 0)
        self.assertEqual(alpha(spec, 'S'), 90)
        self.assertEqual(alpha(spec, 'W'), 180)


class LayoutTests(TestCase):
    def test_long_vessel_is_squeezed_and_positions_map_through_the_courses(self):
        spec = VesselSpec('vertical', 90, courses=[course(120)] * 8 + [{'kind': 'cone', 'length': 60}]
                          + [course(125, diameter=78)] * 4)
        layout = build_layout(spec)
        self.assertEqual(layout.length, 1520)
        self.assertLessEqual(layout.tl_end - layout.tl_start, 4.5 * 100 + 1)
        self.assertAlmostEqual(layout.s_at(0), layout.tl_start)
        self.assertAlmostEqual(layout.s_at(1520), layout.tl_end)
        self.assertAlmostEqual(layout.radius_at(layout.tl_end), 78 / 90 * 50)

    def test_flat_cover_bolted_to_a_flange_has_no_seam(self):
        spec = VesselSpec('exchanger', 30, 'flat', 'ellipsoidal',
                          [{'kind': 'flange'}, course(36), {'kind': 'flange'}, course(96)])
        scene = build_scene(spec)
        seams = [s for s in scene.shapes if s['kind'] == 'circle' and s.get('stroke') == 'seam']
        # flange-channel, channel-flange, flange-shell, shell-head: the cover is bolted
        self.assertEqual(len(seams), 4)


class DrawingTests(TestCase):
    def test_every_type_draws_with_nozzles_and_coverage(self):
        nozzles = [
            {'tag': 'N1', 'size': '8"', 'location': 'shell', 'position': 20, 'direction': 'Top'},
            {'tag': 'N2', 'size': '24"', 'location': 'end', 'position': 0, 'direction': ''},
        ]
        coverage = [{'kind': 'part', 'target': 0}, {'kind': 'seam', 'target': 2}, {'kind': 'nozzle', 'target': 'N1'},
                    {'kind': 'band', 'start': 10, 'end': 50, 'from': 'Top', 'to': 'S', 'style': 'grid', 'label': 'HIC'},
                    {'kind': 'box', 'start': 0, 'end': 60, 'label': 'Examination Area'}]
        for vessel_type in ('horizontal', 'exchanger'):
            spec = VesselSpec(vessel_type, 60, courses=[course(60)] * 3, nozzles=nozzles, boot_diameter=20,
                              boot_length=30, boot_position=90)
            png = render_png(spec, coverage)
            self.assertEqual(Image.open(io.BytesIO(png)).format, 'PNG')
        for vessel_type in ('vertical', 'tank'):
            vertical_nozzles = [dict(nozzles[0], direction='E'), nozzles[1]]
            spec = VesselSpec(vessel_type, 72, 'flat' if vessel_type == 'tank' else 'ellipsoidal', 'cone',
                              courses=[course(96)] * 4, nozzles=vertical_nozzles)
            image = Image.open(io.BytesIO(render_png(spec, [dict(c, **({'from': 'E', 'to': 'W'} if c['kind'] == 'band' else {})) for c in coverage])))
            self.assertGreater(image.height, image.width * 0.8)   # a tall drawing

    def test_tags_and_seam_numbers_are_written(self):
        spec = VesselSpec('horizontal', 66, courses=[course(56)] * 3, seam_start=16,
                          nozzles=[{'tag': 'MH-1', 'size': '24"', 'location': 'shell', 'position': 84, 'direction': 'S'}])
        texts = [s['text'] for s in build_scene(spec).shapes if s['kind'] == 'text']
        self.assertIn('MH-1', texts)
        self.assertEqual([t for t in texts if t.isdigit()], ['16', '17', '18', '19'])


def post_data(**extra):
    data = {'name': '11V-9', 'service': 'Accumulator', 'vessel_type': 'horizontal', 'units': 'imperial',
            'diameter': '66', 'diameter_basis': 'ID', 'start_head': 'ellipsoidal', 'end_head': 'ellipsoidal',
            'supports': 'auto', 'view_from': 'S', 'seam_start': '16', 'boot_diameter': '', 'boot_length': '',
            'boot_position': '', 'notes': '',
            'courses': json.dumps([course(56)] * 3),
            'nozzles': json.dumps([{'tag': 'A', 'size': '8"', 'location': 'shell', 'position': 84, 'direction': 'Top'}])}
    data.update(extra)
    return data


class VesselViewTests(TestCase):
    def test_new_vessel_saves_lengths_in_inches(self):
        response = self.client.post(reverse('new-vessel'), post_data(diameter="5'-6\"", boot_diameter='24',
                                                                     boot_length="3'-4\"", boot_position="7'"))
        vessel = Vessel.objects.get()
        self.assertRedirects(response, reverse('edit-vessel', args=[vessel.pk]))
        self.assertEqual(vessel.diameter, 66)
        self.assertEqual((vessel.boot_diameter, vessel.boot_length, vessel.boot_position), (24, 40, 84))
        self.assertEqual(vessel.length, 168)
        self.assertEqual(vessel.size_text, '66" ID × 14\'-0" T/T')
        page = self.client.get(reverse('edit-vessel', args=[vessel.pk]))
        self.assertContains(page, 'value="66&quot;"')

    def test_rejects_a_nozzle_off_the_shell_or_pointing_along_it(self):
        bad = [{'tag': 'A', 'size': '8"', 'location': 'shell', 'position': 500, 'direction': 'Top'},
               {'tag': 'B', 'size': '8"', 'location': 'shell', 'position': 10, 'direction': 'E'},
               {'tag': 'C', 'size': '2"', 'location': 'boot', 'position': 10, 'direction': 'E'}]
        response = self.client.post(reverse('new-vessel'), post_data(nozzles=json.dumps(bad)))
        self.assertEqual(Vessel.objects.count(), 0)
        errors = response.context['form'].errors['nozzles']
        self.assertTrue(any('off the shell' in e for e in errors))
        self.assertTrue(any('B: pick which way' in e for e in errors))
        self.assertTrue(any('no boot' in e for e in errors))

    def test_needs_a_course_and_a_readable_diameter(self):
        response = self.client.post(reverse('new-vessel'), post_data(courses='[]', diameter='big'))
        form = response.context['form']
        self.assertIn('courses', form.errors)
        self.assertIn('diameter', form.errors)

    def test_preview_draws_unsaved_values_or_names_the_problem(self):
        response = self.client.post(reverse('vessel-preview'), post_data(name=''))
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(Vessel.objects.count(), 0)
        response = self.client.post(reverse('vessel-preview'), post_data(diameter=''))
        self.assertEqual(response.status_code, 400)
        self.assertIn('diameter', response.json()['fields'])

    def test_list_png_duplicate_and_delete(self):
        self.client.post(reverse('new-vessel'), post_data())
        vessel = Vessel.objects.get()
        self.assertEqual(self.client.get(reverse('vessel-png', args=[vessel.pk]))['Content-Type'], 'image/png')
        page = self.client.get(reverse('vessel-list'))
        self.assertContains(page, '11V-9')
        self.assertContains(page, 'Horizontal vessel / drum')
        self.client.post(reverse('vessel-list'), {'selected': [vessel.pk], 'duplicate': ''})
        self.assertTrue(Vessel.objects.filter(name='11V-9 (copy)').exists())
        self.client.post(reverse('vessel-list'), {'selected': list(Vessel.objects.values_list('pk', flat=True)),
                                                  'delete': ''})
        self.assertEqual(Vessel.objects.count(), 0)

    def test_metric_vessel_shows_millimetres(self):
        self.client.post(reverse('new-vessel'), post_data(units='metric', diameter='1676.4'))
        vessel = Vessel.objects.get()
        self.assertAlmostEqual(vessel.diameter, 66)
        self.assertContains(self.client.get(reverse('edit-vessel', args=[vessel.pk])), 'value="1676.4 mm"')
