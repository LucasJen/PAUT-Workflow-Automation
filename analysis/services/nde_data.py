"""
Reads inspection data out of Evident .nde files (HDF5, NDE open format 4.x - https://ndeformat.com)
for the Analysis page. Everything the page shows is built from the A-scan samples and the axis
information here; all values are SI (m, s, m/s, degrees for angles).

Two layouts of A-scan data are read:
    beams   (UCoordinate, Beam, Ultrasound)        sectorial / linear angle-beam (weld) scans
    raster  (UCoordinate, VCoordinate, Ultrasound) 0 deg linear raster (corrosion / HIC) scans
A frame is everything at one scan position: (beams or index positions) x samples. The data is
chunked one scan line at a time, so a frame is one cheap hyperslab read; never load a whole
dataset (files reach 1.3 GB).
"""
import json
import os
from dataclasses import asdict, dataclass, field

import h5py
import numpy as np

BEAMS, RASTER, UNSUPPORTED = 'beams', 'raster', 'unsupported'
STATUS_HAS_DATA, STATUS_SATURATED, STATUS_NO_SYNCHRO = 1, 2, 4


class NdeDataError(Exception):
    """The file can't be read as an .nde file with A-scan data."""


@dataclass
class Axis:
    name: str                 # UCoordinate, VCoordinate, Beam, Ultrasound
    quantity: int
    offset: float = 0.0       # m (U, V) or s (Ultrasound)
    resolution: float = 0.0   # m per step (U, V) or s per sample (Ultrasound)
    label: str = ''           # Scan, Index (from the data mapping), Beam, Ultrasound

    def position(self, i):
        return self.offset + i * self.resolution


@dataclass
class Beam:
    """One beam (or, on a raster scan, one index position's A-scan line)."""
    index: int
    refracted_angle: float = 0.0     # degrees from the normal
    skew_angle: float = 90.0         # degrees; 90 / 270 = towards +V / -V
    velocity: float = 0.0            # m/s in the part
    u_offset: float = 0.0            # m: exit point along the scan axis
    v_offset: float = 0.0            # m: exit point along the index axis
    ultrasound_offset: float = 0.0   # s: time of the first sample
    beam_delay: float = 0.0          # s
    gain: float = 0.0                # dB: the beam's sum gain (+ gain offset)


@dataclass
class Gate:
    id: int
    name: str
    start: float                     # s
    length: float                    # s
    threshold: float                 # % of full screen
    geometry: str = 'SoundPath'
    sync_mode: str = 'Pulse'         # Pulse, or GateRelative (to sync_gate)
    sync_gate: int = None
    trigger: str = ''                # Crossing / MaxPeak for GateRelative


@dataclass
class Group:
    id: int
    name: str
    layout: str                      # beams / raster / unsupported
    reason: str = ''                 # why it's unsupported
    path: str = ''                   # HDF5 path of the amplitude dataset
    status_path: str = ''            # HDF5 path of the A-scan status dataset ('' = none)
    shape: tuple = ()
    axes: list = field(default_factory=list)       # Axis per dimension, storage order
    raw_max: int = 32767             # raw sample value of unit_max
    unit_max: float = 100.0          # e.g. 200 (%) for raw_max
    unit: str = 'Percent'
    beams: list = field(default_factory=list)      # Beam per lateral line (beams, or raster index lines)
    gates: list = field(default_factory=list)
    technique: str = ''              # phased array / conventional
    formation: str = ''              # sectorial / linear / compound / single
    wave_mode: str = ''
    velocity: float = 0.0
    wedge_delay: float = 0.0
    digitizing_frequency: float = 0.0
    rectification: str = ''
    # Pulse: A-scan time from the pulse; SynchroGateRelative: each stored A-scan is already re-timed
    # to its own gate I crossing (t = 0 at the interface, e.g. immersion / HydroFORM)
    synchro_mode: str = 'Pulse'
    # The thickness process's expected range (m) - OmniPC's thickness palette runs over it
    thickness_range: tuple = None

    @property
    def synced_to_interface(self):
        return self.synchro_mode == 'SynchroGateRelative'

    @property
    def scan_axis(self):
        return self.axes[0]

    @property
    def lateral_axis(self):
        return self.axes[1]

    @property
    def ultrasound_axis(self):
        return self.axes[2]


@dataclass
class FileInfo:
    path: str
    size: int
    version: str
    groups: list
    specimen: dict = field(default_factory=dict)   # kind, thickness, outer_radius, velocities (SI)
    weld: dict = field(default_factory=dict)
    scan_pattern: str = ''
    # Where the probe (its wedge's reference point) is: u / v offsets (m) and skew - OmniPC's Index
    # column, and what PA^ is measured from
    probe: dict = field(default_factory=dict)

    def group(self, group_id):
        for g in self.groups:
            if g.id == group_id:
                return g
        raise NdeDataError(f'The file has no group {group_id}.')

    def as_dict(self):
        return asdict(self)


# ── Reading the setup ─────────────────────────────────────────────────────

def _json(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return json.loads(raw)


def _process(group, kind):
    for process in group.get('processes') or []:
        if kind in process:
            return process[kind]
    return None


def _formation(process):
    for mode in ('pulseEcho', 'pitchCatch', 'tandem', 'tofd'):
        technique = process.get(mode)
        if isinstance(technique, dict):
            for key in technique:
                if key.endswith('Formation'):
                    return key[:-len('Formation')]
    return ''


def _gates(process):
    gates = []
    for gate in process.get('gates') or []:
        sync = gate.get('synchronization') or {}
        gates.append(Gate(
            id=gate.get('id', len(gates)), name=gate.get('name', f'Gate {len(gates) + 1}'),
            start=gate.get('start', 0.0), length=gate.get('length', 0.0), threshold=gate.get('threshold', 0.0),
            geometry=gate.get('geometry', 'SoundPath'), sync_mode=sync.get('mode', 'Pulse'),
            sync_gate=sync.get('gateId'), trigger=sync.get('triggeringEvent', ''),
        ))
    return gates


def _axis_labels(setup):
    """{axis name: label} from the data mapping (UCoordinate -> Scan, VCoordinate -> Index)."""
    labels = {}
    for mapping in setup.get('dataMappings') or []:
        for dim in (mapping.get('discreteGrid') or {}).get('dimensions') or []:
            if dim.get('axis') and dim.get('name'):
                labels[dim['axis']] = dim['name']
    return labels


def _group(setup, raw_group, h5):
    gid = raw_group.get('id', 0)
    name = raw_group.get('name') or f'GR-{gid + 1}'
    datasets = raw_group.get('datasets')
    if not datasets:
        return Group(gid, name, UNSUPPORTED, reason='No A-scan datasets (TFM / FMC data is not supported).')
    amplitude = next((d for d in datasets if d.get('dataClass') == 'AScanAmplitude'), None)
    if amplitude is None:
        if any(str(d.get('dataClass', '')).startswith('Tfm') for d in datasets):
            return Group(gid, name, UNSUPPORTED, reason='No A-scan datasets (TFM / FMC data is not supported).')
        return Group(gid, name, UNSUPPORTED, reason='No A-scan amplitude dataset.')
    status = next((d for d in datasets if d.get('dataClass') == 'AScanStatus'), None)
    if amplitude['path'] not in h5:
        return Group(gid, name, UNSUPPORTED, reason=f"Dataset {amplitude['path']} is missing.")
    shape = tuple(h5[amplitude['path']].shape)
    dims = amplitude.get('dimensions') or []
    names = tuple(d.get('axis') for d in dims)
    if names == ('UCoordinate', 'Beam', 'Ultrasound'):
        layout = BEAMS
    elif names == ('UCoordinate', 'VCoordinate', 'Ultrasound'):
        layout = RASTER
    else:
        return Group(gid, name, UNSUPPORTED, reason=f"Unsupported axes {', '.join(map(str, names))}.")
    if len(shape) != 3:
        return Group(gid, name, UNSUPPORTED, reason=f'Unexpected dataset shape {shape}.')

    labels = _axis_labels(setup)
    axes = [Axis(name=d['axis'], quantity=shape[i], offset=d.get('offset', 0.0) or 0.0,
                 resolution=d.get('resolution', 0.0) or 0.0, label=labels.get(d['axis'], d['axis']))
            for i, d in enumerate(dims)]

    technique = 'phased_array'
    process = _process(raw_group, 'ultrasonicPhasedArray')
    if process is None:
        process = _process(raw_group, 'ultrasonicConventional') or {}
        technique = 'conventional'
    process_beams = process.get('beams') or []
    velocity = process.get('velocity', 0.0)

    beams = []
    if layout == BEAMS:
        for i, b in enumerate(dims[1].get('beams') or []):
            pb = process_beams[i] if i < len(process_beams) else {}
            beams.append(Beam(
                index=i, refracted_angle=b.get('refractedAngle', 0.0), skew_angle=b.get('skewAngle', 90.0),
                velocity=b.get('velocity', velocity), u_offset=b.get('uCoordinateOffset', 0.0),
                v_offset=b.get('vCoordinateOffset', 0.0),
                ultrasound_offset=b.get('ultrasoundOffset', pb.get('ascanStart', axes[2].offset)),
                beam_delay=pb.get('beamDelay', 0.0), gain=pb.get('sumGain', 0.0) + (pb.get('gainOffset') or 0.0),
            ))
        if len(beams) != shape[1]:
            return Group(gid, name, UNSUPPORTED, reason=f'{len(beams)} beams described for {shape[1]} in the data.')
    else:
        # Raster: each index position is one A-scan line straight down at its V position
        pb = process_beams[0] if process_beams else {}
        for i in range(shape[1]):
            beams.append(Beam(
                index=i, refracted_angle=pb.get('refractedAngle', 0.0), skew_angle=pb.get('skewAngle', 0.0),
                velocity=velocity, u_offset=0.0, v_offset=axes[1].position(i),
                ultrasound_offset=axes[2].offset, beam_delay=pb.get('beamDelay', 0.0),
                gain=pb.get('sumGain', 0.0) + (pb.get('gainOffset') or 0.0),
            ))
        # The time axis carries its own offset; the lateral axis has no per-beam list
    value = amplitude.get('dataValue') or {}
    return Group(
        id=gid, name=name, layout=layout, path=amplitude['path'],
        status_path=status['path'] if status and status.get('path') in h5 else '',
        shape=shape, axes=axes, raw_max=value.get('max', 32767) or 32767, unit_max=value.get('unitMax', 100.0),
        unit=value.get('unit', 'Percent'), beams=beams, gates=_gates(process), technique=technique,
        formation=_formation(process), wave_mode=process.get('waveMode', ''), velocity=velocity,
        wedge_delay=process.get('wedgeDelay', 0.0), digitizing_frequency=process.get('digitizingFrequency', 0.0),
        rectification=process.get('rectification', ''), synchro_mode=process.get('ascanSynchroMode', 'Pulse'),
        thickness_range=_thickness_range(raw_group),
    )


def _thickness_range(raw_group):
    thickness = _process(raw_group, 'thickness') or {}
    low, high = thickness.get('min'), thickness.get('max')
    return (low, high) if low is not None and high is not None and high > low else None


def _specimen(setup):
    specimens = setup.get('specimens') or []
    if not specimens:
        return {}, {}
    spec = specimens[0]
    for kind in ('plateGeometry', 'pipeGeometry', 'barGeometry', 'unspecifiedGeometry'):
        if kind in spec:
            geometry = spec[kind]
            material = geometry.get('material') or {}
            out = {
                'kind': kind[:-len('Geometry')], 'thickness': geometry.get('thickness'),
                'outer_radius': geometry.get('outerRadius'), 'material': material.get('name', ''),
                'longitudinal_velocity': (material.get('longitudinalWave') or {}).get('nominalVelocity'),
                'shear_velocity': (material.get('transversalVerticalWave') or {}).get('nominalVelocity'),
            }
            return out, spec.get('weldGeometry') or {}
    return {}, spec.get('weldGeometry') or {}


def open_file(path):
    """The file's groups, axes, beams, gates and specimen (no sample data is read)."""
    try:
        with h5py.File(path, 'r') as h5:
            if 'Public/Setup' not in h5:
                raise NdeDataError('Not an .nde file: no /Public/Setup.')
            setup = _json(h5['Public/Setup'][()])
            groups = [_group(setup, g, h5) for g in setup.get('groups') or []]
    except OSError as e:
        raise NdeDataError(f"Couldn't open the file: {e}") from e
    except (ValueError, KeyError, TypeError) as e:
        raise NdeDataError(f"Couldn't read the file's setup: {e}") from e
    specimen, weld = _specimen(setup)
    wedges = setup.get('wedges') or []
    positioning = (wedges[0].get('positioning') or {}) if wedges else {}
    probe = {'u_offset': positioning.get('uCoordinateOffset', 0.0), 'v_offset': positioning.get('vCoordinateOffset', 0.0),
             'skew': positioning.get('skewAngle', 90.0)} if positioning else {}
    patterns = [m.get('discreteGrid', {}).get('scanPattern', '') for m in setup.get('dataMappings') or []]
    return FileInfo(path=os.path.abspath(path), size=os.path.getsize(path), version=setup.get('version', ''),
                    groups=groups, specimen=specimen, weld=weld, scan_pattern=next((p for p in patterns if p), ''),
                    probe=probe)


# ── Reading samples ───────────────────────────────────────────────────────

def _readable(group):
    if group.layout == UNSUPPORTED:
        raise NdeDataError(group.reason or 'This group has no A-scan data that can be shown.')


def read_frame(path, group, scan_index):
    """
    (amplitudes int16 [lateral, samples], status uint8 [lateral] or None) at one scan position.
    """
    _readable(group)
    if not 0 <= scan_index < group.shape[0]:
        raise NdeDataError(f'Scan position {scan_index} is outside 0-{group.shape[0] - 1}.')
    with h5py.File(path, 'r') as h5:
        amplitudes = np.asarray(h5[group.path][scan_index], dtype=np.int16)
        status = np.asarray(h5[group.status_path][scan_index], dtype=np.uint8) if group.status_path else None
    return amplitudes, status


def read_ascan(path, group, scan_index, lateral_index):
    """The A-scan (int16 [samples]) of one beam / index line at one scan position."""
    _readable(group)
    if not (0 <= scan_index < group.shape[0] and 0 <= lateral_index < group.shape[1]):
        raise NdeDataError('That position is outside the data.')
    with h5py.File(path, 'r') as h5:
        return np.asarray(h5[group.path][scan_index, lateral_index], dtype=np.int16)


def read_status(path, group, scan_index, lateral_index):
    """The A-scan's status bits (STATUS_HAS_DATA | STATUS_SATURATED | STATUS_NO_SYNCHRO), or has-data
    when the file has no status dataset."""
    _readable(group)
    if not group.status_path:
        return STATUS_HAS_DATA
    with h5py.File(path, 'r') as h5:
        return int(h5[group.status_path][scan_index, lateral_index])


def usable(group, status):
    """Whether an A-scan with these status bits has readings: it has data, and on a file re-timed
    to the interface its gate I synchronised (OmniPC shows the rest as no data - e.g. the joins
    between a HydroFORM scan's index passes)."""
    status = np.asarray(status)
    ok = (status & STATUS_HAS_DATA).astype(bool)
    if group.synced_to_interface:
        ok &= ~(status & STATUS_NO_SYNCHRO).astype(bool)
    return ok


def to_unit(raw, group):
    """Raw sample values -> the dataset's unit (e.g. % of full screen height)."""
    return np.asarray(raw, dtype=np.float32) * (group.unit_max / group.raw_max)
