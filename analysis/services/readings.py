"""
Gates and OmniPC readings on one A-scan. Definitions confirmed against OmniPC on the user's
HydroFORM sample (31e33a wh 12x12.nde, cell U 118 / V 29: A%1 223.151 %, A/-I/ 0.402 in,
B%1 125.053 %, T(B/-A/) 0.385 in - analysis/tests/fixtures/omnipc_readings/hydroform_31e33a.json):

    crossing   the first sample at or above the gate's threshold, inside the gate - whole samples,
               no interpolation (interpolating gives 0.3842 in for T(B/-A/), OmniPC shows 0.385)
    amplitude  the highest sample inside the gate (X%), in the dataset's unit (raw / max * unitMax;
               the scale can be 200 % or 800 %), whether or not it crosses the threshold
    sync       a GateRelative gate starts `start` after its sync gate's crossing (or peak, for a
               MaxPeak trigger); no crossing there = no gate
    origin     on a SynchroGateRelative file each stored A-scan is already re-timed to its own gate I
               crossing, so gate I's crossing is t = 0 (gate I itself is outside the stored window)
    distance   between two events in true depth: velocity * dt / 2 * cos(refracted angle)

Peak readings, confirmed on the angle-beam sample (ppi 45-19662 fw6 n off1.nde, scan cell 329,
64 deg beam: A% 44.008, SA^ 1.047, DA^ 0.291, PA^ 0.641, ViA^ 0.141 in):
    SA^        sound path to the gate's highest sample: velocity * t / 2 (t from the A-scan start)
    DA^        its depth, folded at the back wall (leg 2 comes back up: 0.459 in -> 0.291 in in a
               0.375 in plate)
    ViA^       index position of the peak: the beam's exit point (vCoordinateOffset) + SA^ sin(angle)
               towards the skew
    PA^        ViA^ measured from the probe's index position (the wedge positioning offset, OmniPC's
               Index column, -0.500 in here): 0.141 - (-0.500) = 0.641
    only when the signal breaks the gate: no crossing of the threshold, no SA^ / DA^ / PA^ / ViA^
               (the user, 2026-10-09); X% is still the gate's highest sample

Floating gates (set on the page, not in OmniPC files): the threshold follows each A-scan's peak at
the ratio it was calibrated at (threshold / reference level), within +/- float_db - see gate_level.

Times are seconds on the A-scan's own time axis (geometry.sample_times).
"""
import math
import re
from dataclasses import dataclass

import numpy as np

from .geometry import fold_depth, ray, sample_times
from .nde_data import to_unit


@dataclass
class GateResult:
    name: str                   # the gate's letter: I, A, B
    found: bool                 # the gate could be placed (its sync gate crossed)
    start: float = None         # s
    end: float = None
    amplitude: float = None     # highest sample in the gate (dataset unit, e.g. %)
    peak_time: float = None     # s, time of that sample (first one, if repeated)
    crossing_time: float = None  # s, first sample at or above the threshold; None = no crossing
    position_time: float = None  # s, where the gate measures from (its detection: edge / peak / max peak)
    threshold: float = 0.0      # a floating gate: its height on this A-scan (None: peak under the floor)
    band: tuple = None          # a floating gate: (lowest, highest) height it may float to

    @property
    def crossed(self):
        return self.crossing_time is not None


def gate_letter(name):
    """'Gate A' -> 'A'."""
    name = (name or '').strip()
    return name.split()[-1].upper() if name else ''


def _order(gates):
    """Gates with their sync gates first."""
    by_id = {g.id: g for g in gates}
    done, ordered = set(), []

    def visit(gate, seen=()):
        if gate.id in done:
            return
        if gate.sync_mode == 'GateRelative' and gate.sync_gate in by_id and gate.sync_gate not in seen:
            visit(by_id[gate.sync_gate], seen + (gate.id,))
        done.add(gate.id)
        ordered.append(gate)

    for gate in gates:
        visit(gate)
    return ordered


def gate_window(gate, beam, group):
    """
    (start, end) A-scan times of a pulse-synced gate on `beam`, or None when the beam misses it.
    SoundPath: the gate's own start / length (the same time window on every beam). TrueDepth: the
    times this beam's ray is between the two depths. Box: the times its ray is inside the box of
    depths and index positions (a beam that doesn't cross the box has no gate).
    """
    if gate.geometry not in ('TrueDepth', 'Box') or gate.depth_start is None or gate.depth_end is None:
        return gate.start, gate.start + gate.length
    r = ray(group, beam)
    d0, d1 = sorted((gate.depth_start, gate.depth_end))
    dz = r.dz if abs(r.dz) > 1e-9 else 1e-9
    lo, hi = d0 / dz, d1 / dz                              # sound path between the depths
    if gate.geometry == 'Box' and gate.index_start is not None and gate.index_end is not None:
        i0, i1 = sorted((gate.index_start, gate.index_end))
        if abs(r.dv) < 1e-12:                              # straight down (0 deg): in or out by its index
            if not i0 <= r.v0 <= i1:
                return None
        else:
            a, b = sorted(((i0 - r.v0) / r.dv, (i1 - r.v0) / r.dv))
            lo, hi = max(lo, a), min(hi, b)
    if hi <= lo or hi <= 0:
        return None
    to_time = 2.0 / beam.velocity
    return max(lo, 0.0) * to_time, hi * to_time


def gate_level(gate, peak):
    """
    The level a signal must reach to break `gate`, given the highest sample in it. A fixed gate: its
    threshold. A floating gate: the threshold's calibrated ratio to the reference (threshold /
    float_ref) times this peak, kept within +/- float_db of the threshold; None (it can't be broken)
    when the peak is under float_floor. `peak` may be a numpy array (NaN = no peak).
    """
    if gate.float_db is None:
        return gate.threshold
    spread = 10 ** (abs(gate.float_db) / 20)
    level = np.clip(gate.threshold / (gate.float_ref or 80.0) * np.asarray(peak, dtype=float),
                    gate.threshold / spread, gate.threshold * spread)
    level = np.where(np.asarray(peak, dtype=float) >= gate.float_floor, level, np.nan)
    if level.ndim:
        return level
    return None if np.isnan(level) else float(level)


def evaluate_gates(group, beam, raw, gates=None, interface=None):
    """
    {letter: GateResult} for a raw A-scan (int16 samples) of `beam` in `group`. `interface`: on a file
    re-timed to the interface, when its gate I crossed (s from the pulse, nde_data.interface_time) - it
    places gate I on the A-scan (without it, gate I has no window to draw).
    """
    gates = group.gates if gates is None else gates
    amplitudes = to_unit(raw, group)
    times = sample_times(group, beam, len(amplitudes))
    results, by_id = {}, {}
    for gate in _order(gates):
        letter = gate_letter(gate.name)
        if gate.sync_mode == 'GateRelative':
            ref = by_id.get(gate.sync_gate)
            event = None
            if ref is not None and ref.found:
                event = ref.peak_time if gate.trigger == 'MaxPeak' else ref.crossing_time
            if event is None:
                by_id[gate.id] = results[letter] = GateResult(letter, False, threshold=gate.threshold)
                continue
            start = event + gate.start
        elif group.synced_to_interface and any(g.sync_gate == gate.id for g in gates):
            # The interface gate of an A-scan re-timed to it: its crossing is the time origin, and its
            # window (set from the pulse) is that far before it
            start = end = None
            if interface is not None:
                start = gate.start - interface
                end = start + gate.length
            by_id[gate.id] = results[letter] = GateResult(
                letter, True, start=start, end=end, crossing_time=0.0,
                peak_time=0.0, position_time=0.0, threshold=gate.threshold)
            continue
        else:
            window = gate_window(gate, beam, group)
            if window is None:   # a box gate this beam doesn't cross: no gate, or (if asked) no amplitude
                zero = gate.geometry == 'Box' and gate.outside == 'zero'
                by_id[gate.id] = results[letter] = GateResult(letter, zero, amplitude=0.0 if zero else None,
                                                              threshold=gate.threshold)
                continue
            start, end = window
        if gate.sync_mode == 'GateRelative':
            end = start + gate.length
        inside = np.nonzero((times >= start) & (times <= end))[0]
        result = GateResult(letter, True, start=start, end=end, threshold=gate.threshold)
        if gate.float_db is not None:
            spread = 10 ** (abs(gate.float_db) / 20)
            result.band = (gate.threshold / spread, gate.threshold * spread)
        if len(inside):
            window = amplitudes[inside]
            top = int(np.argmax(window))
            result.amplitude = float(window[top])
            result.peak_time = float(times[inside[top]])
            level = gate_level(gate, result.amplitude)
            if gate.float_db is not None:
                result.threshold = level   # the height on this A-scan (None: the peak is under the floor)
            over = np.nonzero(window >= level)[0] if level is not None else []
            if len(over):
                result.crossing_time = float(times[inside[over[0]]])
                at = {'edge': over[0], 'maxpeak': top}.get(gate.detection)
                if at is None:   # 'peak': the first peak after the crossing (where the signal stops rising)
                    at = first_peak(window, over[0])
                result.position_time = float(times[inside[at]])
        by_id[gate.id] = results[letter] = result
    return results


def first_peak(window, start):
    """Index of the first peak in `window` from `start`: the last sample before it falls (or the gate ends)."""
    falls = np.nonzero(np.diff(window[start:]) < 0)[0]
    return int(start + falls[0]) if len(falls) else len(window) - 1


def depth_between(beam, t1, t2):
    """True depth (m) between two A-scan times along `beam`."""
    return beam.velocity * (t2 - t1) / 2.0 * math.cos(math.radians(beam.refracted_angle))


_AMPLITUDE = re.compile(r'^([A-Z])%\d*$')               # A%, A%1, B%1
_PEAK = re.compile(r'^(S|D|P|Vi)([A-Z])\^$')            # SA^, DA^, PA^, ViA^
_BETWEEN = re.compile(r'^(?:T\()?([A-Z])/-([A-Z])/\)?$')  # A/-I/, T(B/-A/)


def peak_position(beam, peak_time, thickness=None):
    """(sound path, folded depth, leg, index position) of a gate peak at `peak_time` (m)."""
    sp = beam.velocity * peak_time / 2.0
    angle = math.radians(beam.refracted_angle)
    depth, leg = fold_depth(sp * math.cos(angle), thickness)
    index = beam.v_offset + sp * math.sin(angle) * math.sin(math.radians(beam.skew_angle))
    return sp, depth, leg, index


def omnipc_reading(name, results, beam, info=None):
    """
    The value of an OmniPC reading by its name, from evaluated gates: X% (gate X's amplitude, %),
    X/-Y/ and T(X/-Y/) (true depth between gate Y's and gate X's crossings, m), SX^ / DX^ / ViX^ /
    PX^ (gate X's position: sound path, depth, index position, from the probe; m - DX^ and PX^ need
    `info`, the FileInfo, for the thickness and probe position). A gate's position is where its
    detection puts it - edge, first peak or max peak (OmniPC's ^ readings are its max peak). None when
    the gates involved found nothing; KeyError for a reading not worked out yet.
    """
    match = _PEAK.match(name)
    if match:
        gate = results.get(match.group(2))
        if not (gate and gate.found and gate.position_time is not None and gate.crossed):
            return None   # the position only counts when the signal breaks the gate
        thickness = (info.specimen.get('thickness') if info else None)
        sp, depth, _, index = peak_position(beam, gate.position_time, thickness)
        kind = match.group(1)
        if kind == 'P':
            return index - (info.probe.get('v_offset', 0.0) if info else 0.0)
        return {'S': sp, 'D': depth, 'Vi': index}[kind]
    match = _AMPLITUDE.match(name)
    if match:
        gate = results.get(match.group(1))
        return gate.amplitude if gate and gate.found else None
    match = _BETWEEN.match(name)
    if match:
        later, earlier = results.get(match.group(1)), results.get(match.group(2))
        if not (later and earlier and later.crossed and earlier.crossed):
            return None
        return depth_between(beam, earlier.position_time, later.position_time)
    raise KeyError(name)
