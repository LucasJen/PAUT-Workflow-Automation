import json
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from equipment.cal_due import due_items, parse_text_date, report_cal_warnings
from equipment.models import CalibrationBlock, Encoder, Probe, Scope
from reports.models import Report, ReportProbe, Setup


class CalDueTests(TestCase):
    def test_parse_text_date(self):
        self.assertEqual(parse_text_date('3/15/2027'), date(2027, 3, 15))
        self.assertEqual(parse_text_date('2027-03-15'), date(2027, 3, 15))
        self.assertIsNone(parse_text_date('N/A'))
        self.assertIsNone(parse_text_date(''))

    def test_due_items(self):
        today = date.today()
        Scope.objects.create(name='X3', serial_number='S1', calibration_due_date=today - timedelta(days=1),
                             module_model='MXU', module_serial='M1', module_cal_due=today + timedelta(days=200))
        Probe.objects.create(model='5L64', serial_number='P1', calibration_due_date=today + timedelta(days=10))
        CalibrationBlock.objects.create(block_type='IIW', serial_number='B1', calibration_due_date=today + timedelta(days=90))
        Encoder.objects.create(model='Mini-Wheel', serial_number='E1', calibration_due_date=today + timedelta(days=30))
        items = due_items()
        self.assertEqual([(i['kind'], i['serial'], i['overdue']) for i in items],
                         [('Scope', 'S1', True), ('Probe', 'P1', False), ('Encoder', 'E1', False)])
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, '1 overdue')
        self.assertContains(resp, '1 due soon', count=2)   # the probe and the encoder

    def test_report_warnings_for_equipment_out_of_cal_on_the_test_date(self):
        Scope.objects.create(name='X3', serial_number='QC-1', calibration_due_date=date(2026, 5, 1),
                             module_serial='MOD-1', module_cal_due=date(2027, 1, 1))
        Probe.objects.create(model='5L64', serial_number='p-9', calibration_due_date=date(2026, 5, 30))
        CalibrationBlock.objects.create(block_type='IIW', serial_number='B-7', calibration_due_date=date(2026, 7, 1))
        report = Report.objects.create(test_date=date(2026, 6, 1), inst_serial='qc-1', inst_module_serial='MOD-1',
                                       inst_cal_due='4/30/2026')
        ReportProbe.objects.create(report=report, serial='P-9')
        Setup.objects.create(report=report, cal_block_serial='B-7')
        warnings = report_cal_warnings(report)
        self.assertEqual(len(warnings), 3, warnings)
        self.assertIn('Scope X3 S/N QC-1 was out of calibration (due May 1, 2026) on the test date, Jun 1, 2026.', warnings)
        self.assertTrue(any('Probe 5L64 S/N p-9' in w for w in warnings))
        self.assertTrue(any('Instrument cal. due date on the report (4/30/2026)' in w for w in warnings))

        # In the editor, and with the download
        resp = self.client.get(reverse('create-report'), {'loaded': report.pk})
        self.assertContains(resp, 'was out of calibration')
        with mock.patch('reports.views.reports._render_docx', return_value=b'docx'), \
                mock.patch('reports.views.reports._save_copy'):
            report.report_type = 'paut_long'
            report.save()
            resp = self.client.get(reverse('generate-report', args=[report.pk]))
        self.assertEqual(len(json.loads(resp['X-Report-Warnings'])), 3)

    def test_no_warning_when_in_cal(self):
        Scope.objects.create(serial_number='QC-1', calibration_due_date=date(2027, 5, 1))
        report = Report.objects.create(test_date=date(2026, 6, 1), inst_serial='QC-1', inst_cal_due='5/1/2027')
        self.assertEqual(report_cal_warnings(report), [])


class InventoryPickerTests(TestCase):
    def test_picks_fill_setup_and_weld_fields(self):
        from equipment.pickers import inventory_picks
        Scope.objects.create(name='OmniScan X3', model='X3', serial_number='qc-1', calibration_due_date=date(2027, 1, 16))
        Probe.objects.create(model='5L64', serial_number='P1', frequency='5 MHz', manufacturer='Evident')
        CalibrationBlock.objects.create(block_type='IIW', serial_number='B1', material='Carbon steel')
        Scope.objects.create(model='No serial')
        picks = inventory_picks()
        scope = picks['scopes']['QC-1']
        self.assertEqual((scope['serial'], scope['setup']['scope_model'], scope['setup']['scope_cal_due']),
                         ('qc-1', 'X3', '1/16/2027'))
        self.assertEqual(scope['weld']['inst_name'], 'OmniScan X3')
        self.assertEqual(picks['probes']['P1']['column'], {'model': '5L64', 'make': 'Evident', 'frequency': '5 MHz',
                                                          'serial': 'P1'})
        self.assertEqual(picks['blocks']['B1']['weld']['material'], 'Carbon steel')
        self.assertEqual(len(picks['scopes']), 1)

        resp = self.client.get(reverse('create-report'))
        self.assertContains(resp, '<datalist id="inv-scopes"><option value="qc-1" label="OmniScan X3 · Evident">')
        self.assertContains(self.client.get(reverse('new-setup')), 'inventory_pick.js')
