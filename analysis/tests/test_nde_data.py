import math
import os
import shutil
import tempfile

import numpy as np
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from analysis.paths import PathNotAllowed, allowed_roots, checked_path
from analysis.services import geometry
from analysis.services.nde_data import (
    BEAMS, RASTER, UNSUPPORTED, NdeDataError, open_file, read_ascan, read_frame, to_unit,
)
from analysis.tests import builders


class TempFolderMixin:
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)


class WeldFileTests(TempFolderMixin, TestCase):
    def test_axes_beams_gates_and_specimen_in_si(self):
        path = builders.weld_file(self.folder)
        info = open_file(path)
        self.assertEqual(info.version, '4.1.0')
        group = info.group(0)
        self.assertEqual((group.layout, group.shape, group.formation), (BEAMS, (4, 3, 50), 'sectorial'))
        self.assertEqual([a.name for a in group.axes], ['UCoordinate', 'Beam', 'Ultrasound'])
        self.assertEqual(group.scan_axis.label, 'Scan')
        self.assertAlmostEqual(group.ultrasound_axis.resolution, 5e-8)
        self.assertEqual([b.refracted_angle for b in group.beams], [45.0, 55.0, 65.0])
        beam = group.beams[1]
        self.assertEqual((beam.velocity, beam.skew_angle), (3240.0, 90.0))
        self.assertAlmostEqual(beam.v_offset, -0.0195)
        self.assertAlmostEqual(beam.ultrasound_offset, 4e-6)
        self.assertAlmostEqual(beam.gain, 12.5)
        self.assertEqual((group.raw_max, group.unit_max), (32767, 200.0))
        self.assertEqual([(g.name, g.threshold) for g in group.gates], [('Gate A', 20.0)])
        self.assertEqual(info.specimen['thickness'], 0.0125)
        self.assertEqual(info.specimen['shear_velocity'], 3240.0)
        self.assertIsNone(group.thickness_range)
        self.assertEqual(info.as_dict()['groups'][0]['beams'][0]['refracted_angle'], 45.0)

    def test_frame_and_ascan_are_the_right_slices(self):
        path = builders.weld_file(self.folder)
        group = open_file(path).group(0)
        frame, status = read_frame(path, group, 2)
        self.assertEqual(frame.shape, (3, 50))
        self.assertEqual((frame[0, 0], frame[1, 7], frame[2, 49]), (2000, 2107, 2249))
        self.assertEqual(list(status), [1, 1, 1])
        self.assertEqual(read_frame(path, group, 0)[1][0], 0)   # no data there
        ascan = read_ascan(path, group, 3, 2)
        self.assertEqual((ascan[0], ascan[-1]), (3200, 3249))
        with self.assertRaises(NdeDataError):
            read_frame(path, group, 4)

    def test_raw_values_become_percent(self):
        group = open_file(builders.weld_file(self.folder)).group(0)
        self.assertAlmostEqual(float(to_unit([32767], group)[0]), 200.0, places=3)
        self.assertAlmostEqual(float(to_unit([16383.5], group)[0]), 100.0, places=3)


class RasterFileTests(TempFolderMixin, TestCase):
    def test_index_lines_become_straight_down_beams_at_their_positions(self):
        path = builders.raster_file(self.folder)
        group = open_file(path).group(0)
        self.assertEqual((group.layout, group.shape, group.formation), (RASTER, (5, 4, 40), 'linear'))
        self.assertEqual([a.label for a in group.axes[:2]], ['Scan', 'Index'])
        self.assertAlmostEqual(group.scan_axis.offset, -0.01)
        self.assertEqual([round(b.v_offset, 4) for b in group.beams], [0.0025, 0.0035, 0.0045, 0.0055])
        self.assertTrue(all(b.refracted_angle == 0 and b.velocity == builders.LONGITUDINAL for b in group.beams))
        self.assertAlmostEqual(group.beams[0].ultrasound_offset, -1e-6)
        self.assertEqual([(g.name, g.sync_mode, g.sync_gate) for g in group.gates],
                         [('Gate I', 'Pulse', None), ('Gate A', 'GateRelative', 0)])
        frame, status = read_frame(path, group, 4)
        self.assertEqual((frame.shape, frame[3, 39], status), ((4, 40), 4339, None))


class UnsupportedTests(TempFolderMixin, TestCase):
    def test_tfm_groups_are_listed_as_unsupported(self):
        path = builders.tfm_file(self.folder)
        group = open_file(path).groups[0]
        self.assertEqual(group.layout, UNSUPPORTED)
        self.assertIn('TFM', group.reason)
        with self.assertRaises(NdeDataError):
            read_frame(path, group, 0)

    def test_not_an_nde_file(self):
        path = os.path.join(self.folder, 'x.nde')
        with open(path, 'wb') as f:
            f.write(b'not hdf5')
        with self.assertRaises(NdeDataError):
            open_file(path)


class GeometryTests(TempFolderMixin, TestCase):
    def test_sound_path_depth_and_surface_distance_of_a_45_degree_beam(self):
        group = open_file(builders.weld_file(self.folder)).group(0)
        beam = group.beams[0]                      # 45 deg, exit point at v = -20 mm, first sample at 4 us
        # Sample 20: t = 4 us + 20 * 50 ns = 5 us round trip; SP = 3240 * 5e-6 / 2 = 8.1 mm
        u, v, depth = geometry.position(group, beam, 20)
        sp = 3240 * 5e-6 / 2
        self.assertAlmostEqual(depth, sp * math.cos(math.radians(45)))
        self.assertAlmostEqual(v, -0.02 + sp * math.sin(math.radians(45)))
        self.assertAlmostEqual(u, 0.0)
        times = geometry.sample_times(group, beam)
        self.assertAlmostEqual(times[20], 5e-6)
        self.assertAlmostEqual(float(geometry.sound_path(times[20], beam.velocity)), sp)

    def test_skew_270_runs_the_other_way_and_raster_beams_go_straight_down(self):
        group = open_file(builders.weld_file(self.folder)).group(0)
        beam = group.beams[0]
        beam.skew_angle = 270.0
        self.assertLess(geometry.position(group, beam, 20)[1], beam.v_offset)
        raster = open_file(builders.raster_file(self.folder)).group(0)
        r = geometry.ray(raster, raster.beams[2])
        self.assertAlmostEqual(r.v0, 0.0045)
        self.assertAlmostEqual((r.dv, r.dz), (0.0, 1.0))
        self.assertAlmostEqual(r.sp_step, builders.LONGITUDINAL * 2e-8 / 2)

    def test_depth_folds_at_the_back_wall(self):
        self.assertEqual(geometry.fold_depth(0.004, 0.01), (0.004, 1))
        depth, leg = geometry.fold_depth(0.013, 0.01)          # 3 mm into leg 2: 7 mm deep
        self.assertAlmostEqual(depth, 0.007)
        self.assertEqual(leg, 2)
        depth, leg = geometry.fold_depth(0.025, 0.01)          # leg 3 goes down again
        self.assertAlmostEqual(depth, 0.005)
        self.assertEqual(leg, 3)


class PathTests(TempFolderMixin, TestCase):
    def setUp(self):
        super().setUp()
        from reports.models import WorkingFolder
        WorkingFolder.objects.all().delete()   # a data migration seeds the user's folders

    def test_only_nde_files_inside_working_folders(self):
        from reports.models import WorkingFolder
        jobs = os.path.join(self.folder, 'jobs')
        os.makedirs(jobs)
        inside = builders.weld_file(jobs)
        outside = builders.weld_file(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, os.path.dirname(outside), True)
        WorkingFolder.objects.create(path=os.path.join(self.folder, 'jobs'), report_type='paut_weld')
        self.assertEqual(len(allowed_roots()), 1)
        self.assertTrue(checked_path(inside).endswith('weld.nde'))
        for bad in (outside, os.path.join(self.folder, 'jobs', 'missing.nde'), os.path.join(self.folder, 'jobs', 'x.txt'),
                    os.path.join(self.folder, 'jobs', '..', 'other.nde'), ''):
            with self.assertRaises(PathNotAllowed, msg=bad):
                checked_path(bad)

    @override_settings(ANALYSIS_EXTRA_ROOTS=[])
    def test_page_lists_where_files_can_come_from(self):
        response = self.client.get(reverse('analysis'))
        self.assertContains(response, 'Analysis')
        self.assertContains(response, 'Preferences › Working folders')


class WeldOutlineTests(SimpleTestCase):
    def test_v_bevel_from_the_root_up_with_caps(self):
        weld = {'offset': 0.0024, 'land': {'height': 0.0006}, 'fills': [{'angle': 37.5, 'height': 0.0089}],
                'upperCap': {'width': 0.0202, 'height': 0.002}, 'lowerCap': {'width': 0.0051, 'height': 0.002}}
        lines = geometry.weld_outline(weld, 0.0095)
        left, right, upper, lower = lines
        self.assertEqual(right[0], (0.0024, 0.0095))                     # root face at the back wall
        self.assertAlmostEqual(right[1][1], 0.0089)                      # top of the land
        self.assertAlmostEqual(right[-1][1], 0.0)                        # the fill reaches the surface
        self.assertAlmostEqual(right[-1][0], 0.0024 + 0.0089 * math.tan(math.radians(37.5)))
        self.assertEqual(left[-1][0], -right[-1][0])
        self.assertAlmostEqual(min(y for _, y in upper), -0.002)         # cap above the surface
        self.assertAlmostEqual(max(y for _, y in lower), 0.0095 + 0.002)  # root reinforcement below
        self.assertEqual(geometry.weld_outline({}, 0.01), [])


class ConventionalLineTests(TempFolderMixin, TestCase):
    def test_one_line_reads_as_one_beam_through_frames_ascans_and_the_build(self):
        from analysis.services import projections
        path = builders.conventional_file(self.folder)
        group = open_file(path).group(0)
        self.assertEqual((group.layout, group.shape, group.single, group.technique),
                         (BEAMS, (6, 1, 60), True, 'conventional'))
        self.assertEqual((group.beams[0].refracted_angle, group.beams[0].velocity), (60.0, builders.SHEAR))
        frame, status = read_frame(path, group, 3)
        self.assertEqual((frame.shape, int(frame[0, 5]), list(status)), ((1, 60), 3005, [1]))
        self.assertEqual(int(read_ascan(path, group, 4, 0)[7]), 4007)
        with override_settings(ANALYSIS_CACHE_DIR=os.path.join(self.folder, 'cache')):
            projections.build(path, group, group.gates)
            self.assertEqual(projections.read_cscan(path, group, group.gates)['A_amplitude'].shape, (6, 1))
            self.assertEqual(projections.read_volume_line(path, group, 0)[0].shape, (6, 60))
