"""
Tiny .nde files for tests, written with h5py in a temp folder - never commit real ones. Values are
chosen to hand-check easily: 3240 m/s shear, 5890 m/s longitudinal, round resolutions.
"""
import json
import os
import tempfile

import h5py
import numpy as np

SHEAR, LONGITUDINAL = 3240.0, 5890.0


def _write(path, setup, datasets):
    with h5py.File(path, 'w') as h5:
        h5.create_dataset('Public/Setup', data=json.dumps(setup).encode())
        h5.create_dataset('Properties', data=json.dumps({'methods': []}).encode())
        for name, array in datasets.items():
            chunks = (1,) + array.shape[1:] if array.ndim >= 2 else None
            h5.create_dataset(name, data=array, chunks=chunks)
    return path


def _specimen(thickness):
    return [{'id': 0, 'plateGeometry': {
        'width': 0.3, 'length': 0.3, 'thickness': thickness, 'surfaces': [{'id': 0, 'name': 'Top'}],
        'material': {'name': 'Steel_Mild', 'longitudinalWave': {'nominalVelocity': LONGITUDINAL},
                     'transversalVerticalWave': {'nominalVelocity': SHEAR}, 'density': 7800.0}}}]


def weld_amplitudes(scans=4, beams=3, samples=50):
    """Each sample = scan * 1000 + beam * 100 + sample: any slice says where it came from."""
    s, b, i = np.meshgrid(np.arange(scans), np.arange(beams), np.arange(samples), indexing='ij')
    return (s * 1000 + b * 100 + i).astype(np.int16)


def weld_file(folder=None, scans=4, beams=(45.0, 55.0, 65.0), samples=50, thickness=0.0125,
              ultrasound_offset=4e-6, period=5e-8, status=True):
    """A sectorial weld scan: (UCoordinate, Beam, Ultrasound), skew 90, exit points at -20 mm."""
    folder = folder or tempfile.mkdtemp()
    data = weld_amplitudes(scans, len(beams), samples)
    beam_dims = [{'velocity': SHEAR, 'skewAngle': 90.0, 'refractedAngle': a, 'uCoordinateOffset': 0.0,
                  'vCoordinateOffset': -0.02 + 0.0005 * k, 'ultrasoundOffset': ultrasound_offset}
                 for k, a in enumerate(beams)]
    datasets = [{
        'id': 0, 'dataClass': 'AScanAmplitude', 'storageMode': 'Independent',
        'dataValue': {'min': 0, 'max': 32767, 'unitMin': 0.0, 'unitMax': 200.0, 'unit': 'Percent'},
        'path': '/Public/Groups/0/Datasets/0-AScanAmplitude',
        'dimensions': [{'axis': 'UCoordinate', 'quantity': scans, 'resolution': 0.001},
                       {'axis': 'Beam', 'beams': beam_dims},
                       {'axis': 'Ultrasound', 'quantity': samples, 'resolution': period}],
    }]
    arrays = {'Public/Groups/0/Datasets/0-AScanAmplitude': data}
    if status:
        datasets.append({'id': 1, 'dataClass': 'AScanStatus', 'storageMode': 'Independent',
                         'path': '/Public/Groups/0/Datasets/1-AScanStatus',
                         'dataValue': {'hasData': 1, 'saturated': 2, 'noSynchro': 4, 'unit': 'Bitfield'},
                         'dimensions': datasets[0]['dimensions'][:2]})
        flags = np.ones((scans, len(beams)), dtype=np.uint8)
        flags[0, 0] = 0          # no data at the first position of the first beam
        arrays['Public/Groups/0/Datasets/1-AScanStatus'] = flags
    setup = {
        'version': '4.1.0', 'groups': [{
            'id': 0, 'name': 'GR-1', 'datasets': datasets,
            'processes': [{'id': 0, 'ultrasonicPhasedArray': {
                'pulseEcho': {'sectorialFormation': {'beamRefractedAngles': {'start': beams[0], 'stop': beams[-1]}}},
                'waveMode': 'TransversalVertical', 'velocity': SHEAR, 'wedgeDelay': 0.0,
                'digitizingFrequency': 1e8, 'rectification': 'Full',
                'beams': [{'id': k, 'refractedAngle': a, 'ascanStart': ultrasound_offset, 'beamDelay': 7e-6,
                           'sumGain': 12.0, 'gainOffset': 0.5} for k, a in enumerate(beams)],
                'gates': [{'id': 1, 'name': 'Gate A', 'geometry': 'SoundPath', 'synchronization': {'mode': 'Pulse'},
                           'start': 5e-6, 'length': 1e-5, 'threshold': 20.0}],
            }}],
        }],
        'dataMappings': [{'id': 0, 'discreteGrid': {'scanPattern': 'OneLineScan', 'dimensions': [
            {'axis': 'UCoordinate', 'name': 'Scan', 'offset': 0.0, 'quantity': scans, 'resolution': 0.001}]}}],
        'specimens': _specimen(thickness),
    }
    return _write(os.path.join(folder, 'weld.nde'), setup, arrays)


def raster_file(folder=None, scans=5, index=4, samples=40, thickness=0.0254,
                u_offset=-0.01, v_offset=0.0025, us_offset=-1e-6, period=2e-8):
    """A 0 deg raster (corrosion) scan: (UCoordinate, VCoordinate, Ultrasound)."""
    folder = folder or tempfile.mkdtemp()
    data = weld_amplitudes(scans, index, samples)
    dims = [{'axis': 'UCoordinate', 'offset': u_offset, 'quantity': scans, 'resolution': 0.001},
            {'axis': 'VCoordinate', 'offset': v_offset, 'quantity': index, 'resolution': 0.001},
            {'axis': 'Ultrasound', 'offset': us_offset, 'quantity': samples, 'resolution': period}]
    setup = {
        'version': '4.1.0', 'groups': [{
            'id': 0, 'name': 'GR-1', 'datasets': [{
                'id': 0, 'dataClass': 'AScanAmplitude', 'storageMode': 'Paintbrush',
                'dataValue': {'min': 0, 'max': 32767, 'unitMin': 0.0, 'unitMax': 200.0, 'unit': 'Percent'},
                'path': '/Public/Groups/0/Datasets/0-AScanAmplitude', 'dimensions': dims}],
            'processes': [{'id': 0, 'ultrasonicPhasedArray': {
                'pulseEcho': {'linearFormation': {}}, 'waveMode': 'Longitudinal', 'velocity': LONGITUDINAL,
                'beams': [{'id': k, 'refractedAngle': 0.0, 'skewAngle': 0.0, 'ascanStart': us_offset, 'sumGain': 20.0}
                          for k in range(index)],
                'gates': [{'id': 0, 'name': 'Gate I', 'start': 1.5e-5, 'length': 1e-5, 'threshold': 40.0,
                           'synchronization': {'mode': 'Pulse'}},
                          {'id': 1, 'name': 'Gate A', 'start': 2.6e-6, 'length': 8.6e-6, 'threshold': 20.0,
                           'synchronization': {'mode': 'GateRelative', 'triggeringEvent': 'Crossing', 'gateId': 0}}],
            }}],
        }],
        'dataMappings': [{'id': 0, 'discreteGrid': {'scanPattern': 'OneLineScan', 'dimensions': [
            {'axis': 'UCoordinate', 'name': 'Scan'}, {'axis': 'VCoordinate', 'name': 'Index'}]}}],
        'specimens': _specimen(thickness),
    }
    return _write(os.path.join(folder, 'raster.nde'), setup, {'Public/Groups/0/Datasets/0-AScanAmplitude': data})


def tfm_file(folder=None):
    """A TFM capture: a group without A-scan datasets."""
    folder = folder or tempfile.mkdtemp()
    setup = {'version': '4.1.0', 'groups': [{'id': 1, 'processes': []}]}
    return _write(os.path.join(folder, 'tfm.nde'), setup,
                  {'Public/Groups/1/Datasets/0-TfmValue': np.zeros((2, 3, 4), dtype=np.int16)})
