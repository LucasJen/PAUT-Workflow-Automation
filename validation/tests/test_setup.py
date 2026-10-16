"""L1 setups: OmniPC's setup.csv against what the app reads - equal to the digit, and a changed value fails."""
import os
import shutil
import tempfile

from django.test import TestCase

from analysis.tests import builders
from validation import importer, runner
from validation.kit import Kit

# The builder's weld file: 12.5 mm (0.492 in) plate, 3240 m/s (0.1276 in/us), 50 ns samples (20 MHz),
# 50 points, beams 45 / 55 / 65 deg, gate A 5 us + 10 us of time (0.319 in + 0.638 in of sound path), 20 %
SETUP = """﻿Part & Weld
Material,Steel/ Mild,Part Type,Flat Weld,
Thickness,{thickness} in,Length,11.811 in,

Setup
Law Config.,PA,Averaging Factor,1,Gain,{gain} dB,
Beam Delay,7.00 us,Compression,1,Points Quantity,50,
Effect. Digit. Frequency,100 MHz,Video Filter,Off,Wave Type,Shear,
Net Digit. Frequency,20.0 MHz,Range True Depth,1.000 in.,Range Sound Path,1.000 in.,
Rectification,Absolute,Velocity,0.1276 in./µs,Acq. Rate,120.0 Hz,
Delta Vt,0.0 dB,Gates,Start,Width,Threshold,Synchro,Peak Selection,
A,0.319 in.,0.638 in.,20 %,Pulse,Highest,

Calculator
Law Configuration,Sectorial,Element Step,- ,Angle Resolution,10.0 °,
Element Qty Used,16,Start Angle,45.0 °,Focus Depth,0.375 in.,
First Element,1,Stop Angle,65.0 °,Focusing Type,True Depth,
"""


class SetupTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        source = os.path.join(self.folder, 'source')
        os.makedirs(source)
        self.kit = Kit(os.path.join(self.folder, 'kit'))
        self.nde = self.kit.add(builders.weld_file(source), ['decoding'], 'synthetic')

    def l1(self, **values):
        path = os.path.join(self.folder, 'setup.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(SETUP.format(**{'thickness': '0.492', 'gain': '0.0', **values}))
        importer.import_setup(self.kit, path, self.nde, 'synthetic export')
        run = runner.execute(runner.create(['L1'], self.kit.root))
        return run, run.results['layers'][0]['checks']

    def test_the_setup_as_omnipc_shows_it_passes(self):
        run, checks = self.l1()
        self.assertEqual(run.status, 'passed', [i for c in checks for i in c['items'] if i['ok'] is False])
        compared = {i['what'] for i in checks[0]['items']}
        self.assertTrue({'Thickness', 'Points Quantity', 'Velocity', 'Net Digit. Frequency', 'Start Angle', 'Stop Angle',
                         'Angle Resolution', 'Wave Type', 'Gate A start (sound path)', 'Gate A width (sound path)',
                         'Gate A threshold', 'Gate A synchro'} <= compared, compared)

    def test_a_different_thickness_fails(self):
        run, checks = self.l1(thickness='0.500')
        self.assertEqual(run.status, 'failed')
        self.assertEqual([i['what'] for i in checks[0]['items'] if i['ok'] is False], ['Thickness'])

    def test_a_file_kept_outside_the_kit_and_gone_is_not_used_not_failed(self):
        outside = os.path.join(self.folder, 'outside')
        os.makedirs(outside)
        entry = self.kit.add(builders.raster_file(outside), ['decoding'], 'elsewhere', copy=False)
        self.assertTrue(entry.get('in_place'))
        shutil.rmtree(outside)
        run = runner.execute(runner.create(['L0'], self.kit.root))
        self.assertEqual(run.status, 'passed')
        self.assertIn(None, [f['ok'] for f in run.results['kit']['files']])
