"""The weld report's Sensitivity block & test material card: library blocks, Auto-detect, TCG, Excel."""
import json

from django.test import TestCase
from django.urls import reverse

from equipment.models import SensitivityBlock
from reports.materials import block_values, detect_block, part_values
from reports.models import Report
from reports.services.excel_report import weld_pages
from reports.weld_columns import scanned_part
from reports.weld_form import tcg_distances


def block(**fields):
    values = dict(pipe_size='6in Sch 40', serial_number='19019', block_type='Notch', material='Carbon Steel',
                  velocity_shear='0.128 in/μs', velocity_long='0.232 in/μs', cal_diameter='6.625"',
                  cal_sch_nom='Sch 40 / 0.280"', cal_thickness='0.280', temperature='65', surface_cal='Machined',
                  surface_test='As Welded / Smooth', couplant='Water', bevel_geometry='37 °', encoder='Jireh Microbe',
                  encoder_steps='482.97', scan_res='0.039"', scan_speed='≤2in/s', test_diameter='6.625"',
                  test_thickness='0.280', test_sch_nom='Sch 40 / 0.280"', reflector_depth='0.280')
    values.update(fields)
    return SensitivityBlock.objects.create(**values)


class DetectTests(TestCase):
    def setUp(self):
        SensitivityBlock.objects.all().delete()
        self.sch40 = block()
        self.sch80 = block(pipe_size='6in Sch 80', serial_number='19020', test_thickness='0.432', cal_thickness='0.432')
        self.two_inch = block(pipe_size='2in Sch 40', serial_number='19001', test_diameter='2.375"', test_thickness='0.154')

    def test_block_by_diameter_then_wall(self):
        self.assertEqual(detect_block({'od': 6.625, 'thickness': 0.28})[0], self.sch40)
        self.assertEqual(detect_block({'od': 6.625, 'thickness': 0.43})[0], self.sch80)
        self.assertEqual(detect_block({'od': 2.375, 'thickness': 0.15})[0], self.two_inch)

    def test_no_block_for_the_diameter_or_no_scan(self):
        self.assertIsNone(detect_block({'od': 12.75, 'thickness': 0.375})[0])
        self.assertIn('import an .nde first', detect_block({})[1])

    def test_closest_wall_is_offered_with_a_note(self):
        found, why = detect_block({'od': 6.625, 'thickness': 0.35})
        self.assertIn(found, (self.sch40, self.sch80))
        self.assertIn('closest', why)

    def test_plate_specimens_use_the_pipe_size_or_a_unique_wall(self):
        # no OD: two 6in blocks share nothing, but 0.280 is only the Sch 40 here; 2in by its wall
        self.assertEqual(detect_block({'thickness': 0.28}, '6in Sch 40')[0], self.sch40)
        self.assertEqual(detect_block({'thickness': 0.43}, '6" Sch 80')[0], self.sch80)
        self.assertEqual(detect_block({'thickness': 0.154})[0], self.two_inch)
        block(pipe_size='8in Sch 20', serial_number='19030', test_diameter='8.625"', test_thickness='0.280')
        found, why = detect_block({'thickness': 0.28})
        self.assertIsNone(found)
        self.assertIn('enter the NPS / Sch', why)
        self.assertIsNone(detect_block({'thickness': 0.28}, '12in')[0])

    def test_part_values_from_the_scan(self):
        values = part_values({'od': 6.625, 'thickness': 0.28, 'material': 'Carbon steel', 'shear_velocity': 0.1276,
                              'bevel_angle': 37.5}, self.sch40)
        # the wall is the block's, so its 'Sch 40 / 0.280"' stays
        self.assertEqual(values, {'item_diameter': '6.625"', 'item_material': 'Carbon steel',
                                  'item_vel_shear': '0.128 in/μs', 'item_bevel': '37.5 °'})
        self.assertEqual(part_values({'thickness': 0.32}, self.sch40)['item_sch_nom'], '0.320"')

    def test_endpoint(self):
        data = self.client.post(reverse('detect-sensitivity-block'),
                                {'scan_part': json.dumps({'od': 6.625, 'thickness': 0.28, 'source': 'w5.nde'})}).json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['values']['sensitivity_block'], self.sch40.pk)
        self.assertEqual((data['values']['tcg_block'], data['values']['tcg_thickness']), ('19019', '0.280'))
        self.assertEqual(data['encoder']['inst_encoder_cal'], '482.97')
        self.assertIn('w5.nde', data['message'])
        self.assertFalse(self.client.post(reverse('detect-sensitivity-block'), {'scan_part': 'nonsense'}).json()['ok'])
        data = self.client.post(reverse('detect-sensitivity-block'),
                                {'scan_part': json.dumps({'thickness': 0.432}), 'pipe_size': '6in'}).json()
        self.assertEqual(data['values']['sensitivity_block'], self.sch80.pk)


class ScannedPartTests(TestCase):
    def test_inches_whatever_the_units(self):
        self.assertEqual(scanned_part({'units': 'imperial', 'specimen_od': '6.625', 'specimen_thickness': '0.280',
                                       'sound_velocity': '0.1276', 'wave_propagation': 'Shear',
                                       'cal_material': 'Carbon steel', 'weld_bevel_angle': '37.5',
                                       'source_file': 'w5.nde'}),
                         {'od': 6.625, 'thickness': 0.28, 'material': 'Carbon steel', 'shear_velocity': 0.1276,
                          'bevel_angle': 37.5, 'source': 'w5.nde'})
        part = scanned_part({'units': 'metric', 'specimen_od': '168.28', 'specimen_thickness': '7.11',
                             'sound_velocity': '5890', 'wave_propagation': 'Longitudinal'})
        self.assertEqual((part['od'], part['thickness'], part['long_velocity']), (6.6252, 0.2799, 0.2319))


class MaterialCellsTests(TestCase):
    def test_tcg_points_are_1t_2t_3t(self):
        self.assertEqual(tcg_distances('0.280"'), ['0.280', '0.560', '0.840'])
        self.assertEqual(tcg_distances(''), [])

    def test_card_prints_its_cells(self):
        values = {k: v for k, v in block_values(block()).items() if k != 'sensitivity_block'}
        report = Report.objects.create(report_type='paut_weld', item_exam_surface='O.D.', cal_std_exam_surface='O.D.',
                                       add1_block_type='10 Step', add1_serial='51349', add2_block_type='Mini IIW Block',
                                       tcg_amplitude='0.8', **values)
        cells = weld_pages(report).report
        self.assertEqual((cells['U15'], cells['W14'], cells['W16'], cells['Y16'], cells['Y20'], cells['Y26']),
                         ('6in Sch 40', '19019', 'Notch', 'N/A', '6.625"', '37 °'))
        self.assertEqual((cells['W24'], cells['W28'], cells['W29'], cells['Y28']),
                         ('O.D.', '10 Step', '51349', 'Mini IIW Block'))
        self.assertEqual((cells['L34'], cells['Q34'], cells['L35'], cells['P35']), ('19019', '19019', 'Notch', 'Notch'))
        self.assertEqual((cells['L36'], cells['N36'], cells['P36'], cells['N37']), ('0.280', '0.560', '0.840', '0.8'))

    def test_reports_without_the_card_print_the_scan_plans_block(self):
        from reports.models import ScanPlan
        plan = ScanPlan.objects.create(name='p', thickness=0.28, sensitivity_block=block())
        cells = weld_pages(Report.objects.create(report_type='paut_weld', scan_plan=plan)).report
        self.assertEqual((cells['W14'], cells['L36']), ('19019', '0.280'))


class CardPagesTests(TestCase):
    def test_editor_and_defaults_show_the_card(self):
        page = self.client.get(reverse('create-report'))
        self.assertContains(page, 'id="sec-materials"')
        self.assertContains(page, 'id="materials-detect"')
        self.assertContains(page, 'name="add2_serial"')
        defaults = self.client.get(reverse('new-defaults', args=['paut_weld']))
        self.assertContains(defaults, 'id="materials-card"')
        self.assertNotContains(defaults, 'id="materials-detect"')
        self.assertNotContains(self.client.get(reverse('new-defaults', args=['paut_long'])), 'id="materials-card"')

    def test_defaults_keep_the_card(self):
        from reports.models import ReportDefaults
        sch40 = block()
        self.client.post(reverse('new-defaults', args=['paut_weld']), {
            'defaults_name': 'Standard', 'sensitivity_block': sch40.pk, 'add1_block_type': '10 Step',
            'tcg_amplitude': '0.8'})
        values = ReportDefaults.objects.get().report_values
        self.assertEqual((values['sensitivity_block'], values['add1_block_type'], values['tcg_amplitude']),
                         (sch40.pk, '10 Step', '0.8'))
