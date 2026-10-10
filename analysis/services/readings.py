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

Times are seconds on the A-scan's own time axis (geometry.sample_times).
"""
import math
import re
from dataclasses import dataclass

import numpy as np

from .geometry import fold_depth, sample_times
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
    threshold: float = 0.0

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


def evaluate_gates(group, beam, raw, gates=None):
    """{letter: GateResult} for a raw A-scan (int16 samples) of `beam` in `group`."""
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
            # The interface gate of an A-scan re-timed to it: its crossing is the time origin
            by_id[gate.id] = results[letter] = GateResult(
                letter, True, start=gate.start, end=gate.start + gate.length, crossing_time=0.0,
                peak_time=0.0, threshold=gate.threshold)
            continue
        else:
            start = gate.start
        end = start + gate.length
        inside = np.nonzero((times >= start) & (times <= end))[0]
        result = GateResult(letter, True, start=start, end=end, threshold=gate.threshold)
        if len(inside):
            window = amplitudes[inside]
            top = int(np.argmax(window))
            result.amplitude = float(window[top])
            result.peak_time = float(times[inside[top]])
            over = np.nonzero(window >= gate.threshold)[0]
            if len(over):
                result.crossing_time = float(times[inside[over[0]]])
        by_id[gate.id] = results[letter] = result
    return results


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
    PX^ (gate X's peak: sound path, depth, index position, from the probe; m - DX^ and PX^ need
    `info`, the FileInfo, for the thickness and probe position). None when the gates involved found
    nothing; KeyError for a reading not worked out yet.
    """
    match = _PEAK.match(name)
    if match:
        gate = results.get(match.group(2))
        if not (gate and gate.found and gate.peak_time is not None and gate.crossed):
            return None   # the peak only counts when the signal breaks the gate
        thickness = (info.specimen.get('thickness') if info else None)
        sp, depth, _, index = peak_position(beam, gate.peak_time, thickness)
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
        return depth_between(beam, earlier.crossing_time, later.crossing_time)
    raise KeyError(name)
