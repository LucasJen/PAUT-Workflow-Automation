"""
NDE metadata extraction. The main fixture is metadata from a real MXU raster scan
(linear PA on a plate); the other cases are built from the NDE format 4.x schema
(https://ndeformat.com) to cover pipe/bar specimens, sectorial scans, TOFD and missing data.
"""
from django.test import SimpleTestCase

from reports.models import Setup
from reports.services.nde_parser import extract_groups
from reports.tests.test_nde_upload import FIXTURE, sample_setup

SETUP_FIELDS = {f.name for f in Setup._meta.concrete_fields}


class RealFileTests(SimpleTestCase):
    """Linear PA raster scan on a 25.4 mm plate (OmniScan X3 / 7.5L64-I4 / HydroFORM)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        [cls.group] = extract_groups(FIXTURE['setup'], FIXTURE['properties'], 'sample raster scan.nde')
        cls.imp = cls.group['values']['imperial']
        cls.met = cls.group['values']['metric']

    def test_every_key_is_a_setup_field(self):
        self.assertLessEqual(set(self.imp) | set(self.met), SETUP_FIELDS)

    def test_label(self):
        self.assertEqual(self.group['label'], 'GR-1 · Linear · 0°')

    def test_equipment(self):
        self.assertEqual(self.imp['manufacturer'], 'Evident')
        self.assertEqual(self.imp['scope_platform'], 'OmniScan X3')
        self.assertEqual(self.imp['scope_model'], 'OmniScan X3 64 - 64:128PR')
        self.assertEqual(self.imp['scope_serial'], 'QC-0000000')
        self.assertEqual(self.imp['transducer_model'], '7.5L64-I4')
        self.assertEqual(self.imp['wedge_model'], 'HydroFORM')
        self.assertEqual(self.imp['wedge_angle'], '0')
        self.assertNotIn('transducer_serial', self.imp)  # not recorded in this file

    def test_bare_numbers_because_template_adds_units(self):
        # The Word template writes {{FREQ}} MHz and {{X_RES}}" etc.
        self.assertEqual(self.imp['freq'], '7.5')
        self.assertEqual(self.imp['x_res'], '0.0394')
        self.assertEqual(self.met['x_res'], '1.000')

    def test_ut_settings(self):
        self.assertEqual(self.imp['foc_depth'], '0.300')
        self.assertEqual(self.met['foc_depth'], '7.62')
        self.assertEqual(self.imp['wave_propagation'], 'Longitudinal')
        self.assertEqual(self.imp['elements'], '64')
        self.assertEqual(self.imp['sound_velocity'], '0.2319')
        self.assertEqual(self.met['sound_velocity'], '5890')
        self.assertEqual(self.imp['voltage'], '5')

    def test_group_and_beam_gain_are_separate(self):
        self.assertEqual(self.imp['gain'], '0')
        self.assertEqual(self.imp['beam_gain'], '27.1')
        self.assertEqual(self.imp['ref_gain'], '0')

    def test_raster_scan_area_from_data_mapping(self):
        self.assertEqual(self.imp['scan_pattern'], 'Raster scan')
        self.assertEqual(self.met['scan_length'], '306.00')
        self.assertEqual(self.met['scan_width'], '306.00')
        self.assertEqual(self.imp['y_res'], '0.0394')

    def test_linear_formation(self):
        self.assertEqual(self.imp['beam_formation'], 'Linear')
        self.assertEqual(self.imp['active_elements'], '1–64')
        self.assertEqual(self.imp['element_aperture'], '4')
        self.assertEqual(self.imp['element_step'], '1')
        self.assertEqual(self.imp['angle_range'], '0°')
        self.assertNotIn('angle_step', self.imp)  # no angle sweep in a linear scan

    def test_acquisition_details(self):
        self.assertEqual(self.imp['pulse_width'], '65')
        self.assertEqual(self.imp['digitizing_frequency'], '100')
        self.assertEqual(self.imp['band_pass_filter'], '4–12')
        self.assertEqual(self.imp['calibrations'], 'TCG')
        self.assertEqual(self.imp['gates'], 'I: 6.82–25.79 µs, 30%; A: 1.29–8.19 µs, 20%; B: 5–11.9 µs, 20%')
        self.assertEqual(self.imp['encoder_resolution'], 'Scan 189.97 steps/in; Index 0.5 steps/in')
        self.assertEqual(self.met['encoder_resolution'], 'Scan 7.48 steps/mm; Index 0.02 steps/mm')

    def test_plate_specimen_and_thickness_range(self):
        self.assertEqual(self.imp['specimen_thickness'], '1.000')
        self.assertEqual(self.met['specimen_thickness'], '25.40')
        self.assertEqual(self.met['specimen_dimensions'], '300.0 × 300.0 mm')
        self.assertEqual(self.imp['cal_material'], 'Steel Mild')
        self.assertNotIn('specimen_od', self.imp)  # plates have no OD
        self.assertEqual(self.imp['tr_min'], '0.250')
        self.assertEqual(self.imp['tr_max'], '0.400')
        self.assertEqual(self.met['tr_min'], '6.35')

    def test_source(self):
        self.assertEqual(self.imp['source_file'], 'sample raster scan.nde')
        self.assertEqual(self.imp['acquisition_date'], '2026-09-22 09:28')


def pa_group(formation, beams, group_id=0, name='GR-1', mapping_id=0):
    return {
        'id': group_id, 'name': name,
        'processes': [{
            'id': 0, 'dataMappingId': mapping_id,
            'ultrasonicPhasedArray': {
                'pulseEcho': {'probeId': 0, **formation},
                'waveMode': 'TransversalVertical', 'velocity': 3240.0, 'gain': 12.0,
                'beams': beams,
            },
        }],
    }


class OtherLayoutTests(SimpleTestCase):
    def test_sectorial_on_pipe_with_tofd_group(self):
        beams = [{'id': i, 'refractedAngle': 40.0 + i, 'sumGain': 20.0 + i * 0.1} for i in range(31)]
        setup = {
            'groups': [
                pa_group({'sectorialFormation': {
                    'probeFirstElementId': 0, 'elementAperture': 16,
                    'beamRefractedAngles': {'start': 40.0, 'stop': 70.0, 'step': 1.0},
                }}, beams),
                {'id': 1, 'name': 'TOFD', 'processes': [{'id': 2, 'dataMappingId': 0, 'ultrasonicConventional': {
                    'tofd': {'pulserProbeId': 1, 'receiverProbeId': 2, 'pcs': 0.0508},
                    'waveMode': 'Longitudinal', 'velocity': 5890.0, 'gain': 40.0,
                    'beams': [{'id': 0, 'refractedAngle': 60.0}],
                }}]},
            ],
            'probes': [
                {'id': 0, 'model': '5L16-A10', 'serialNumber': 'P123',
                 'phasedArrayLinear': {'centralFrequency': 5e6, 'primaryAxis': {'elementQuantity': 16}}},
                {'id': 1, 'model': 'C543-SM', 'conventionalRound': {'centralFrequency': 5e6, 'diameter': 0.00635}},
            ],
            'specimens': [{'id': 0, 'pipeGeometry': {
                'thickness': 0.0127, 'outerRadius': 0.1143, 'length': 1.0,
                'material': {'name': 'Carbon_Steel'},
            }}],
            'dataMappings': [{'id': 0, 'specimenId': 0, 'discreteGrid': {
                'scanPattern': 'OneLineScan',
                'dimensions': [{'axis': 'UCoordinate', 'quantity': 500, 'resolution': 0.001, 'name': 'Scan'}],
            }}],
        }
        pa, tofd = extract_groups(setup)

        self.assertEqual(pa['label'], 'GR-1 · Sectorial · 40°–70°')
        v = pa['values']['imperial']
        self.assertEqual(v['angle_range'], '40°–70°')
        self.assertEqual(v['angle_step'], '1°')
        self.assertEqual(v['active_elements'], '1–16')
        self.assertEqual(v['beam_gain'], '20–23')
        self.assertEqual(v['gain'], '12')
        self.assertEqual(v['wave_propagation'], 'Shear')
        self.assertEqual(v['specimen_od'], '9.000')
        self.assertEqual(v['cal_material'], 'Carbon Steel')
        self.assertEqual(v['scan_pattern'], 'One line scan')
        self.assertEqual(pa['values']['metric']['scan_length'], '500.00')
        self.assertEqual(pa['values']['metric']['specimen_dimensions'], '1000.0 mm long')

        self.assertEqual(tofd['label'], 'TOFD · TOFD · 60°')
        t = tofd['values']['imperial']
        self.assertEqual(t['beam_formation'], 'TOFD')
        self.assertEqual(t['pcs'], '2.000')
        self.assertEqual(t['transducer_model'], 'C543-SM')
        self.assertEqual(t['probe_diameter'], '0.250')
        self.assertEqual(t['elements'], '1')
        self.assertEqual(t['freq'], '5')

    def test_bar_diameter_is_od(self):
        setup = {
            'groups': [pa_group({}, [])],
            'specimens': [{'id': 0, 'barGeometry': {'diameter': 0.05, 'length': 0.3}}],
        }
        [group] = extract_groups(setup)
        self.assertEqual(group['values']['metric']['specimen_od'], '50.00')

    def test_sparse_file_does_not_crash(self):
        [group] = extract_groups({'groups': [{'id': 0}]})
        self.assertEqual(group['label'], 'Group 1')
        self.assertEqual(group['values']['imperial'], {'units': 'imperial'})  # only the unit system

    def test_every_extracted_key_is_a_setup_field(self):
        for group in extract_groups(sample_setup(), FIXTURE['properties'], 'x.nde'):
            for values in group['values'].values():
                self.assertLessEqual(set(values), SETUP_FIELDS)


class TimeBaseTests(SimpleTestCase):
    """The weld form's Time base (A-scan start - range, half path in the part) and Points quantity."""

    def ut(self, setup):
        group = setup['groups'][0]
        process = next(p for p in group['processes'] if 'ultrasonicPhasedArray' in p or 'ultrasonicConventional' in p)
        return group, process.get('ultrasonicPhasedArray') or process.get('ultrasonicConventional')

    def test_start_and_range_as_the_reference_writes_them(self):
        setup = sample_setup()
        _, ut = self.ut(setup)
        ut['velocity'] = 3240.0                      # PPI 31-37575 W5: the reference shows 0.269 in - 1.75 in
        ut['beams'][0].update(ascanStart=4.22e-06, ascanLength=2.744e-05)
        values = extract_groups(setup)[0]['values']
        self.assertEqual(values['imperial']['time_base'], '0.269 in - 1.75 in')
        self.assertEqual(values['metric']['time_base'], '6.84 mm - 44.45 mm')

    def test_points_from_the_ascan_dataset_else_worked_out(self):
        setup = sample_setup()
        self.assertEqual(extract_groups(setup)[0]['values']['imperial']['points_quantity'], '1036')
        group, ut = self.ut(setup)
        group['datasets'] = []
        ut.update(digitizingFrequency=100e6, ascanCompressionFactor=2)
        ut['beams'][0]['ascanLength'] = 2.744e-05
        self.assertEqual(extract_groups(setup)[0]['values']['imperial']['points_quantity'], '1372')


class WeldFormValueTests(SimpleTestCase):
    """Group values the weld form shows: Focal plane, Amplitude range and Reference dB from the file."""

    def setup_with(self, mode='TrueDepth', unit_max=800.0, ref_gain=10.6, gain=16.6):
        setup = sample_setup()
        group = setup['groups'][0]
        process = next(p for p in group['processes'] if 'ultrasonicPhasedArray' in p or 'ultrasonicConventional' in p)
        ut = process.get('ultrasonicPhasedArray') or process.get('ultrasonicConventional')
        ut['focusing'] = {'mode': mode, 'distance': 0.0107}
        ut['referenceGain'], ut['gain'] = ref_gain, gain
        group['datasets'][0]['dataValue'] = {'min': 0, 'max': 32767, 'unitMin': 0.0, 'unitMax': unit_max, 'unit': 'Percent'}
        return setup

    def test_focal_plane_and_amplitude_range(self):
        values = extract_groups(self.setup_with())[0]['values']['imperial']
        self.assertEqual((values['focal_plane'], values['amplitude_range']), ('Depth', '800%'))
        self.assertEqual(extract_groups(self.setup_with(mode='HalfPath'))[0]['values']['imperial']['focal_plane'], 'Half path')

    def test_reference_db_is_the_reference_gain(self):
        from reports.weld_columns import columns_from_setup
        values = extract_groups(self.setup_with())[0]['values']['imperial']
        self.assertEqual(columns_from_setup(values)['group']['reference_db'], '10.6 dB')
        self.assertEqual(columns_from_setup({'gain': '12'})['group']['reference_db'], '12 dB')   # older setups
