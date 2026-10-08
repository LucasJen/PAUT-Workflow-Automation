"""
Reads setup information from Evident .nde files for the "Import from NDE" page.

An .nde file is HDF5. Its setup is a JSON document at /Public/Setup and file details are at
/Properties (NDE open format 4.x, https://ndeformat.com). All values in the file are SI
(metres, seconds, Hz, m/s). Values are returned as bare numbers because the Word template
supplies the units (e.g. {{X_RES}}" and {{FREQ}} MHz); compound fields carry their own units.

Each inspection group in the file becomes one candidate setup, in both unit systems:
    [{'id': 0, 'label': 'GR-1 · Linear 0°',
      'values': {'imperial': {field: text}, 'metric': {field: text}}}, ...]
Field names match reports.models.Setup.
"""
import io
import json
import re

import h5py

M_TO_IN = 39.37007874
UNIT_SYSTEMS = ('imperial', 'metric')

# The instrument's focusing modes as the weld form's Focal plane names them
FOCUS_MODES = {
    'TrueDepth': 'Depth',
    'HalfPath': 'Half path',
    'ProjectionDistance': 'Projection',
    'FocalPlane': 'Plane',
}

FORMATION_NAMES = {
    'sectorialFormation': 'Sectorial',
    'linearFormation': 'Linear',
    'compoundFormation': 'Compound',
    'singleFormation': 'Single',
}

CALIBRATION_NAMES = {
    'sensitivityCalibration': 'Sensitivity',
    'tcgCalibration': 'TCG',
    'velocityCalibration': 'Velocity',
    'wedgeDelayCalibration': 'Wedge delay',
    'dacCalibration': 'DAC',
    'dgsCalibration': 'DGS',
    'tofdWedgeDelayCalibration': 'TOFD wedge delay',
}


class NdeError(Exception):
    """The file can't be read as an .nde file with setup metadata."""


# ── Reading the file ─────────────────────────────────────────────────────

def _load_json(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return json.loads(raw)


def read_nde(uploaded):
    """
    Returns (setup, properties) dicts from an uploaded .nde file. Large uploads are read
    from Django's temporary file so only the metadata is loaded, not the scan data.
    """
    if hasattr(uploaded, 'temporary_file_path'):
        source = uploaded.temporary_file_path()
    else:
        source = io.BytesIO(uploaded.read())
    try:
        with h5py.File(source, 'r') as f:
            if 'Public/Setup' not in f:
                raise NdeError('No Setup metadata found in this .nde file.')
            setup = _load_json(f['Public/Setup'][()])
            properties = _load_json(f['Properties'][()]) if 'Properties' in f else {}
    except NdeError:
        raise
    except Exception as e:
        raise NdeError(f'Failed to parse file: {e}') from e
    return setup, properties


# ── Helpers ──────────────────────────────────────────────────────────────

def _get(obj, *keys):
    """Nested lookup through dicts and lists; None if any step is missing."""
    for key in keys:
        if obj is None:
            return None
        try:
            obj = obj[key]
        except (KeyError, IndexError, TypeError):
            return None
    return obj


def _by_id(items, item_id):
    """The item with this id, else the first item, else {}."""
    items = items or []
    for item in items:
        if item.get('id') == item_id:
            return item
    return items[0] if items else {}


def _mm(metres):
    return None if metres is None else round(metres * 1000, 3)


def _plain(x, decimals=3):
    """Compact number: 5.0 -> '5', 7.5 -> '7.5', 0.23188 -> '0.232'."""
    if x is None:
        return None
    text = f'{x:.{decimals}f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def _dist(metres, system, in_dec=3, mm_dec=2):
    if metres is None:
        return None
    return f'{metres * M_TO_IN:.{in_dec}f}' if system == 'imperial' else f'{metres * 1000:.{mm_dec}f}'


def _length_unit(system):
    return 'in' if system == 'imperial' else 'mm'


def _deg(x):
    return None if x is None else f'{_plain(x, 2)}°'


def _drop_empty(value):
    """The dict / list without None, '' and empty containers (recursively)."""
    if isinstance(value, dict):
        value = {k: _drop_empty(v) for k, v in value.items()}
        return {k: v for k, v in value.items() if v not in (None, '', {}, [])}
    if isinstance(value, list):
        return [_drop_empty(v) for v in value]
    return value


def _range(low, high, fmt):
    if low is None or high is None:
        return None
    return fmt(low) if low == high else f'{fmt(low)}–{fmt(high)}'


def _words(camel):
    """'RasterScan' -> 'Raster scan'."""
    text = re.sub(r'(?<!^)(?=[A-Z])', ' ', camel or '').lower()
    return text[:1].upper() + text[1:] if text else None


# ── Extraction ───────────────────────────────────────────────────────────

def extract_groups(setup, properties=None, filename=''):
    """One candidate setup per inspection group, in imperial and metric."""
    properties = properties or {}
    groups = []
    for group in setup.get('groups') or []:
        context = _GroupContext(setup, properties, group, filename)
        groups.append({
            'id': group.get('id'),
            'label': context.label(),
            'values': {system: context.values(system) for system in UNIT_SYSTEMS},
            'hardware': context.hardware(),
        })
    return groups


class _GroupContext:
    """Resolves the probe, wedge, specimen, data mapping, etc. that one group refers to."""

    def __init__(self, setup, properties, group, filename):
        self.setup = setup
        self.properties = properties
        self.group = group
        self.filename = filename

        processes = group.get('processes') or []
        self.ut_process = next(
            (p for p in processes if 'ultrasonicPhasedArray' in p or 'ultrasonicConventional' in p), {},
        )
        self.is_pa = 'ultrasonicPhasedArray' in self.ut_process
        self.ut = self.ut_process.get('ultrasonicPhasedArray') or self.ut_process.get('ultrasonicConventional') or {}
        self.thickness = next((p['thickness'] for p in processes if 'thickness' in p), {})

        # Acquisition pattern: pulse-echo, pitch-catch, tandem or TOFD
        self.pattern_name, self.pattern = next(
            ((k, self.ut[k]) for k in ('pulseEcho', 'pitchCatch', 'tandem', 'tofd') if k in self.ut), (None, {}),
        )
        probe_id = self.pattern.get('probeId', self.pattern.get('pulserProbeId'))
        self.probe = _by_id(setup.get('probes'), probe_id)
        self.probe_tech = next(
            (self.probe[k] for k in ('phasedArrayLinear', 'conventionalRound', 'conventionalRectangular') if k in self.probe),
            {},
        )
        association = self.probe.get('wedgeAssociation') or {}
        self.wedge = _by_id(setup.get('wedges'), association.get('wedgeId'))
        self.mounting = _by_id(_get(self.wedge, 'angleBeamWedge', 'mountingLocations'), association.get('mountingLocationId'))
        self.unit = _by_id(setup.get('acquisitionUnits'), None)

        self.mapping = _by_id(setup.get('dataMappings'), self.ut_process.get('dataMappingId'))
        self.specimen = _by_id(setup.get('specimens'), self.mapping.get('specimenId'))
        self.geometry_name, self.geometry = next(
            ((k, v) for k, v in self.specimen.items() if k.endswith('Geometry') and isinstance(v, dict)), (None, {}),
        )

        # Beam formation (phased array)
        self.formation_name, self.formation = next(
            ((k, self.pattern[k]) for k in FORMATION_NAMES if k in self.pattern), (None, {}),
        )

    # ── Scan axes ──

    def _axis(self, axis):
        """(resolution m, quantity, motionDeviceId, name) for UCoordinate (scan) or VCoordinate (index)."""
        for dim in _get(self.mapping, 'discreteGrid', 'dimensions') or []:
            if dim.get('axis') == axis:
                return dim.get('resolution'), dim.get('quantity'), dim.get('motionDeviceId'), dim.get('name')
        # Fall back to the first dataset's dimensions (e.g. one-line scans list beams on VCoordinate)
        for dim in _get(self.group, 'datasets', 0, 'dimensions') or []:
            if dim.get('axis') == axis:
                quantity = dim.get('quantity') or len(dim.get('beams') or []) or None
                return dim.get('resolution'), quantity, None, None
        return None, None, None, None

    # ── Angles / technique ──

    def _angles(self):
        """(angle_range, angle_step) text."""
        if self.formation_name == 'linearFormation' or self.formation_name == 'singleFormation':
            return _deg(self.formation.get('beamRefractedAngle')), None
        angles = self.formation.get('beamRefractedAngles')
        if isinstance(angles, dict):
            return _range(angles.get('start'), angles.get('stop'), _deg), _deg(angles.get('step'))
        refracted = [b.get('refractedAngle') for b in self.ut.get('beams') or [] if b.get('refractedAngle') is not None]
        if not refracted:
            return None, None
        step = abs(refracted[1] - refracted[0]) if len(refracted) > 1 and refracted[1] != refracted[0] else None
        return _range(min(refracted), max(refracted), _deg), _deg(step)

    def technique(self):
        if self.pattern_name == 'tofd':
            return 'TOFD'
        if self.formation_name:
            return FORMATION_NAMES[self.formation_name]
        if self.ut_process and not self.is_pa:
            return 'Conventional'
        return None

    def label(self):
        angle_range, _ = self._angles()
        parts = [self.group.get('name') or f"Group {self.group.get('id', 0) + 1}", self.technique(), angle_range]
        return ' · '.join(p for p in parts if p)

    # ── Values ──

    def values(self, system):
        ut, probe_tech, geometry = self.ut, self.probe_tech, self.geometry
        unit = _length_unit(system)
        angle_range, angle_step = self._angles()
        scan_res, scan_qty, scan_device, scan_name = self._axis('UCoordinate')
        index_res, index_qty, index_device, index_name = self._axis('VCoordinate')

        freq = probe_tech.get('centralFrequency')
        filter_ = ut.get('digitalBandPassFilter') or {}

        values = {
            # Equipment
            'manufacturer': _get(self.properties, 'file', 'createdByAppCompany'),
            'scope_platform': self.unit.get('platform'),
            'scope_model': self.unit.get('model'),
            'scope_serial': self.unit.get('serialNumber'),
            'software_version': self._software_version(),
            'scanner_model': self._scanner(scan_device),
            'transducer_model': self.probe.get('model'),
            'transducer_serial': self.probe.get('serialNumber'),
            'probe_diameter': self._probe_size(system),
            'wedge_model': self.wedge.get('model'),
            'wedge_angle': _plain(self.mounting.get('wedgeAngle'), 2),
            # SI in both unit systems (mm, m/s): the scan plan draws with these
            'wedge_primary_offset': _mm(self.mounting.get('primaryOffset')),
            'wedge_first_element_height': _mm(self.mounting.get('tertiaryOffset')),
            'wedge_velocity': _get(self.wedge, 'angleBeamWedge', 'longitudinalVelocity'),
            'wedge_length': _mm(_get(self.wedge, 'angleBeamWedge', 'length')),
            'wedge_height': _mm(_get(self.wedge, 'angleBeamWedge', 'height')),

            # UT settings
            'foc_depth': _dist(_get(ut, 'focusing', 'distance'), system, 3, 2),
            'wave_propagation': {'Longitudinal': 'Longitudinal', 'TransversalVertical': 'Shear'}.get(ut.get('waveMode')),
            'freq': _plain(freq / 1e6, 2) if freq else None,
            'elements': self._elements(),
            'x_res': _dist(scan_res, system, 4, 3),
            'y_res': _dist(index_res, system, 4, 3),
            'scan_length': _dist(scan_res * scan_qty, system, 3, 2) if scan_res and scan_qty else None,
            'scan_width': _dist(index_res * index_qty, system, 3, 2) if index_res and index_qty else None,
            'angle_step': angle_step,
            'angle_range': angle_range,
            'sound_velocity': self._velocity(system),
            'gain': _plain(ut.get('gain'), 1),
            'beam_gain': self._beam_gain(),
            'ref_gain': _plain(ut.get('referenceGain'), 1),
            'voltage': _plain(_get(ut, 'pulse', 'voltage'), 1),
            'time_base': self._time_base(system),
            'focal_plane': FOCUS_MODES.get(_get(ut, 'focusing', 'mode')),
            'amplitude_range': self._amplitude_range(),
            'points_quantity': self._points_quantity(),

            # Acquisition
            'beam_formation': self.technique(),
            'active_elements': self._active_elements(),
            'element_aperture': _plain(self.formation.get('elementAperture'), 0),
            'element_step': _plain(self.formation.get('elementStep'), 2),
            'pcs': _dist(_get(ut, 'tofd', 'pcs'), system, 3, 2),
            'scan_pattern': _words(_get(self.mapping, 'discreteGrid', 'scanPattern')),
            'encoder_resolution': self._encoders(system, [(scan_name or 'Scan', scan_device), (index_name or 'Index', index_device)]),
            'digitizing_frequency': _plain(ut['digitizingFrequency'] / 1e6, 2) if ut.get('digitizingFrequency') else None,
            'pulse_width': _plain(_get(ut, 'pulse', 'width') * 1e9, 1) if _get(ut, 'pulse', 'width') else None,
            'band_pass_filter': self._filter(filter_),
            'gates': self._gates(),
            'calibrations': self._calibrations(),

            # Specimen
            'specimen_od': self._outer_diameter(system),
            'specimen_thickness': _dist(geometry.get('thickness'), system, 3, 2),
            'units': system,
            **self._weld(system),
            'index_offset': self._index_offset(system),
            'specimen_dimensions': self._specimen_dimensions(system, unit),
            'cal_material': (_get(geometry, 'material', 'name') or '').replace('_', ' ') or None,
            'tr_min': _dist(self.thickness.get('min'), system, 3, 2),
            'tr_max': _dist(self.thickness.get('max'), system, 3, 2),

            # Source
            'source_file': self.filename or None,
            'acquisition_date': self._date(),
            # Everything the instrument's setup report shows, for the report's setup sheet (setup_sheet.py)
            'nde_sheet': self._sheet_json(),
        }
        return {k: str(v) for k, v in values.items() if v not in (None, '')}

    # ── Setup sheet ──

    def sheet(self):
        """
        The group's setup as the instrument's setup report lists it (instrument, probe and wedge,
        UT settings, gates, TCG, focal laws) plus what the setup sheet's drawing needs, in the
        file's own SI units (m, s, Hz, m/s); setup_sheet.py formats it in the setup's units.
        """
        ut, beams = self.ut, self.ut.get('beams') or []
        first_beam = beams[0] if beams else {}
        primary = _get(self.probe_tech, 'primaryAxis') or {}
        compression = ut.get('ascanCompressionFactor')
        digitizing = ut.get('digitizingFrequency')
        angle_range, angle_step = self._angles()
        scan_res, _, _, scan_name = self._axis('UCoordinate')
        index_res, _, _, index_name = self._axis('VCoordinate')
        sheet = {
            'v': 1,
            'group': self.group.get('name') or f"Group {self.group.get('id', 0) + 1}",
            'technique': self.technique(),
            'file': self.filename or None,
            'date': self._date(),
            'calibrations': self._calibrations(),
            'instrument': {
                'platform': self.unit.get('platform'),
                'model': self.unit.get('model'),
                'serial': self.unit.get('serialNumber'),
                'software': ' '.join(str(v) for v in (_get(self.properties, 'file', 'createdByAppName'),
                                                      _get(self.properties, 'file', 'createdByAppVersion')) if v),
                'acquisition_rate': self.unit.get('acquisitionRate'),
            },
            'probe': {
                'model': self.probe.get('model'),
                'serial': self.probe.get('serialNumber') or self.probe.get('serie'),
                'frequency': self.probe_tech.get('centralFrequency'),
                'elements': primary.get('elementQuantity') or (1 if self.probe_tech else None),
                'pitch': (primary['elementLength'] + (primary.get('elementGap') or 0))
                if primary.get('elementLength') is not None else None,
                'size': self.probe_tech.get('diameter') or self.probe_tech.get('length'),
                'skew': _get(self.wedge, 'positioning', 'skewAngle'),
                'scan_offset': _get(self.wedge, 'positioning', 'uCoordinateOffset'),
                'index_offset': _get(self.wedge, 'positioning', 'vCoordinateOffset'),
            },
            'wedge': {
                'model': self.wedge.get('model'),
                'serial': self.wedge.get('serialNumber') or self.wedge.get('serie'),
                'angle': self.mounting.get('wedgeAngle'),
                'velocity': _get(self.wedge, 'angleBeamWedge', 'longitudinalVelocity'),
                'length': _get(self.wedge, 'angleBeamWedge', 'length'),
                'height': _get(self.wedge, 'angleBeamWedge', 'height'),
                'primary_offset': self.mounting.get('primaryOffset'),
                'first_element_height': self.mounting.get('tertiaryOffset'),
            },
            'part': {
                'material': (_get(self.geometry, 'material', 'name') or '').replace('_', ' ') or None,
                'thickness': self.geometry.get('thickness'),
                'od': self.geometry['outerRadius'] * 2 if self.geometry.get('outerRadius') is not None else None,
            },
            'ut': {
                'mode': {'pulseEcho': 'PE (Pulse-Echo)', 'pitchCatch': 'PC (Pitch-Catch)', 'tofd': 'TOFD',
                         'tandem': 'Tandem'}.get(self.pattern_name),
                'wave_mode': {'TransversalVertical': 'Shear'}.get(ut.get('waveMode'), ut.get('waveMode')),
                'velocity': ut.get('velocity'),
                'gain': ut.get('gain'),
                'reference_gain': ut.get('referenceGain'),
                'reference_amplitude': ut.get('referenceAmplitude'),
                'beam_delay': first_beam.get('beamDelay'),
                'wedge_delay': ut.get('wedgeDelay'),
                'ascan_start': first_beam.get('ascanStart'),
                'ascan_length': first_beam.get('ascanLength'),
                'ultrasound_mode': ut.get('ultrasoundMode'),
                'digitizing': digitizing,
                'net_digitizing': digitizing / compression if digitizing and compression else None,
                'compression': compression,
                'points': self._points_quantity(),
                'averaging': ut.get('averagingFactor'),
                'rectification': ut.get('rectification'),
                'filter': self._filter(ut.get('digitalBandPassFilter') or {}),
                'smoothing': self._smoothing(),
                'pulse_width': _get(ut, 'pulse', 'width'),
                'voltage': _get(ut, 'pulse', 'voltage'),
                'polarity': _words(_get(ut, 'pulse', 'polarity')),
            },
            'gates': self._sheet_gates(),
            'tcg': [[p.get('time'), p.get('gain')] for p in _get(first_beam, 'tcg', 'points') or []
                    if p.get('time') is not None],
            'law': {
                'formation': self.technique(),
                'first_element': self.formation['probeFirstElementId'] + 1
                if self.formation.get('probeFirstElementId') is not None else None,
                'last_element': self.formation['probeLastElementId'] + 1
                if self.formation.get('probeLastElementId') is not None else None,
                'aperture': self.formation.get('elementAperture'),
                'element_step': self.formation.get('elementStep'),
                'angles': angle_range,
                'angle_step': angle_step,
                'focus_mode': FOCUS_MODES.get(_get(ut, 'focusing', 'mode'), _get(ut, 'focusing', 'mode')),
                'focus_distance': _get(ut, 'focusing', 'distance'),
            },
            'axes': {
                'scan': {'name': scan_name or 'Scan', 'resolution': scan_res} if scan_res else None,
                'index': {'name': index_name or 'Index', 'resolution': index_res} if index_res else None,
            },
            'beams': self._sheet_beams(),
        }
        sheet = _drop_empty(sheet)
        # Nothing the instrument recorded (a sparse or unknown layout): no sheet
        return sheet if any(k in sheet for k in ('instrument', 'probe', 'ut', 'beams')) else None

    def _sheet_json(self):
        sheet = self.sheet()
        return json.dumps(sheet, ensure_ascii=False, separators=(',', ':')) if sheet else None

    def _smoothing(self):
        smoothing = self.ut.get('smoothingFilter')
        if isinstance(smoothing, dict):
            return 'On' if smoothing.get('enabled', True) else 'Off'
        if isinstance(smoothing, (int, float)) and not isinstance(smoothing, bool):
            return f'{_plain(smoothing / 1e6, 2)} MHz' if smoothing else 'Off'   # the filter's frequency, Hz
        return None if smoothing is None else str(smoothing)

    def _sheet_gates(self):
        """[{name, start, length (s), threshold %, synchro}] in the file's order."""
        gates = self.ut.get('gates') or []
        names = {g.get('id'): re.sub(r'^Gate\s+', '', g.get('name') or '') for g in gates}
        rows = []
        for gate in gates:
            start, length = gate.get('start'), gate.get('length')
            if start is None and gate.get('starts'):        # per-beam gates: the first beam's
                start, length = gate['starts'][0], (gate.get('lengths') or [None])[0]
            sync = gate.get('synchronization') or {}
            if sync.get('mode') == 'GateRelative':
                synchro = f"Gate {names.get(sync.get('gateId'), '?')} {_words(sync.get('triggeringEvent')) or ''}".strip()
            else:
                synchro = _words(sync.get('mode'))
            rows.append({'name': names.get(gate.get('id')) or f"#{gate.get('id')}", 'start': start, 'length': length,
                         'threshold': gate.get('threshold'), 'synchro': synchro})
        return rows

    def _sheet_beams(self):
        """[[aperture centre element (0-based), refracted angle]] per focal law, for the sheet's drawing."""
        out = []
        for beam in self.ut.get('beams') or []:
            elements = [p['elementId'] for p in beam.get('pulsers') or [] if p.get('elementId') is not None]
            if elements and beam.get('refractedAngle') is not None:
                out.append([round(sum(elements) / len(elements), 2), round(beam['refractedAngle'], 2)])
        return out

    def _amplitude_range(self):
        """The A-scan's full scale, as the weld form writes it: '800%'."""
        for dataset in self.group.get('datasets') or []:
            value = dataset.get('dataValue') or {}
            if value.get('unit') == 'Percent' and value.get('unitMax') is not None:
                return f"{_plain(value['unitMax'], 1)}%"
        return None

    def _software_version(self):
        """The instrument software that recorded the file, as the weld form writes it: '5.20.0.1413' -> '5.20.0'."""
        version = _get(self.properties, 'file', 'createdByAppVersion')
        return '.'.join(str(version).split('.')[:3]) if version else None

    def _scanner(self, device_id):
        """The scan axis' motion device (the scanner / encoder name set on the instrument, e.g. Cobra)."""
        devices = self.setup.get('motionDevices') or []
        device = _by_id(devices, device_id) if device_id is not None else (devices[0] if len(devices) == 1 else {})
        return device.get('name') or None

    def _time_base(self, system):
        """
        The A-scan's start and range as half-path distance in the part, as the weld form writes
        them ('0.269 in - 1.75 in', OmniScan's Start / Range): the first beam's ascanStart and
        ascanLength (round-trip seconds) at the part velocity.
        """
        beam = (self.ut.get('beams') or [{}])[0]
        start, length, velocity = beam.get('ascanStart'), beam.get('ascanLength'), self.ut.get('velocity')
        if start is None or length is None or not velocity:
            return None
        to_path = lambda seconds: seconds * velocity / 2   # metres
        if system == 'imperial':
            return f'{_plain(to_path(start) * M_TO_IN, 3)} in - {_plain(to_path(length) * M_TO_IN, 3)} in'
        return f'{_plain(to_path(start) * 1000, 2)} mm - {_plain(to_path(length) * 1000, 2)} mm'

    def _points_quantity(self):
        """Samples per A-scan: the A-scan dataset's Ultrasound axis (else length × digitizing rate ÷ compression)."""
        for dataset in self.group.get('datasets') or []:
            for dim in dataset.get('dimensions') or []:
                if dim.get('axis') == 'Ultrasound' and dim.get('quantity'):
                    return str(dim['quantity'])
        length = ((self.ut.get('beams') or [{}])[0]).get('ascanLength')
        rate = self.ut.get('digitizingFrequency')
        if length and rate:
            return str(round(length * rate / (self.ut.get('ascanCompressionFactor') or 1)))
        return None

    def _probe_size(self, system):
        if 'diameter' in self.probe_tech:
            return _dist(self.probe_tech['diameter'], system, 3, 2)
        if 'length' in self.probe_tech and 'width' in self.probe_tech:
            return f"{_dist(self.probe_tech['length'], system, 3, 2)} × {_dist(self.probe_tech['width'], system, 3, 2)}"
        return None

    def _elements(self):
        if 'phasedArrayLinear' in self.probe:
            return _plain(_get(self.probe_tech, 'primaryAxis', 'elementQuantity'), 0)
        return '1' if self.probe_tech else None

    def hardware(self):
        """
        The probe and wedge this group used, as stored in the file (for matching them to the
        probe / wedge catalogue), with the wedge mounting position and the aperture.
        """
        association = self.probe.get('wedgeAssociation') or {}
        first = self.formation.get('probeFirstElementId')
        last = self.formation.get('probeLastElementId')
        aperture = self.formation.get('elementAperture')
        if aperture is None and first is not None and last is not None:
            aperture = last - first + 1
        return {
            'probe': self.probe,
            'wedge': self.wedge,
            'mounting_id': association.get('mountingLocationId'),
            'first_element': first + 1 if first is not None else None,  # file ids are 0-based
            'aperture': aperture,
        }

    def _weld(self, system):
        """
        The specimen's weld definition (OmniScan V weld): bevel angle of the fill, land height as
        the root face, and twice the weld offset (centre line to the bevel at the root) as the root
        gap. The cap width isn't taken: OmniScan's default (about 43 mm) is rarely changed, so the
        scan plan calculates it from the bevel instead.
        """
        weld = self.specimen.get('weldGeometry') or {}
        fills = weld.get('fills') or [{}]
        offset = weld.get('offset')
        values = {
            'weld_bevel_angle': _plain(fills[0].get('angle'), 1),
            'weld_root_face': _dist(_get(weld, 'land', 'height'), system, 3, 2),
            'weld_root_gap': _dist(2 * offset, system, 3, 2) if offset is not None else None,
        }
        return {k: v for k, v in values.items() if v is not None}

    def _index_offset(self, system):
        """Wedge front to the weld centre line: the wedge's position across the weld (either side)."""
        offset = _get(self.wedge, 'positioning', 'vCoordinateOffset')
        return _dist(abs(offset), system, 3, 2) if offset is not None else None

    def _active_elements(self):
        first = self.formation.get('probeFirstElementId')
        last = self.formation.get('probeLastElementId')
        aperture = self.formation.get('elementAperture')
        if first is None:
            return None
        if last is None and aperture:
            last = first + aperture - 1
        return None if last is None else f'{first + 1}–{last + 1}'  # file ids are 0-based

    def _velocity(self, system):
        velocity = self.ut.get('velocity')
        if velocity is None:
            return None
        return f'{velocity / 25400:.4f}' if system == 'imperial' else f'{velocity:.0f}'  # in/µs or m/s

    def _beam_gain(self):
        gains = [
            b['sumGain'] + (b.get('gainOffset') or 0)
            for b in self.ut.get('beams') or [] if b.get('sumGain') is not None
        ]
        if not gains:
            return None
        return _range(round(min(gains), 1), round(max(gains), 1), lambda g: _plain(g, 1))

    def _encoders(self, system, axes):
        parts = []
        for name, device_id in axes:
            if device_id is None:
                continue
            steps = _get(_by_id(self.setup.get('motionDevices'), device_id), 'encoder', 'stepResolution')
            if steps is None:
                continue
            per_unit = steps / M_TO_IN if system == 'imperial' else steps / 1000  # steps/m -> steps/in or /mm
            parts.append(f'{name} {_plain(per_unit, 2)} steps/{_length_unit(system)}')
        return '; '.join(parts) or None

    @staticmethod
    def _filter(filter_):
        kind = filter_.get('filterType')
        low, high = filter_.get('lowCutOffFrequency'), filter_.get('highCutOffFrequency')
        if kind == 'BandPass' and low is not None and high is not None:
            return f'{_plain(low / 1e6, 2)}–{_plain(high / 1e6, 2)}'
        if kind == 'LowPass' and high is not None:
            return f'Low-pass {_plain(high / 1e6, 2)}'
        if kind == 'HighPass' and low is not None:
            return f'High-pass {_plain(low / 1e6, 2)}'
        return 'None' if kind == 'None' else None

    def _gates(self):
        parts = []
        for gate in self.ut.get('gates') or []:
            name = re.sub(r'^Gate\s+', '', gate.get('name') or f"#{gate.get('id')}")
            start, length = gate.get('start'), gate.get('length')
            text = name
            if start is not None and length is not None:
                text += f': {_plain(start * 1e6, 2)}–{_plain((start + length) * 1e6, 2)} µs'
            if gate.get('threshold') is not None:
                text += f', {_plain(gate["threshold"], 1)}%'
            parts.append(text)
        return '; '.join(parts) or None

    def _calibrations(self):
        states = self.ut.get('calibrationStates')
        if not states:
            return None
        done = [
            CALIBRATION_NAMES.get(key, _words(key))
            for state in states for key, value in state.items()
            if isinstance(value, dict) and value.get('calibrated')
        ]
        return ', '.join(done) or 'None'

    def _outer_diameter(self, system):
        if self.geometry.get('outerRadius') is not None:
            return _dist(self.geometry['outerRadius'] * 2, system, 3, 2)
        if self.geometry_name == 'barGeometry':
            return _dist(self.geometry.get('diameter'), system, 3, 2)
        return None

    def _specimen_dimensions(self, system, unit):
        length, width = self.geometry.get('length'), self.geometry.get('width')
        if length is not None and width is not None:
            return f'{_dist(length, system, 3, 1)} × {_dist(width, system, 3, 1)} {unit}'
        if length is not None:
            return f'{_dist(length, system, 3, 1)} {unit} long'
        return None

    def _date(self):
        created = _get(self.properties, 'file', 'creationDate')
        if not created:
            return None
        match = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})', created)
        return f'{match.group(1)} {match.group(2)}' if match else created
