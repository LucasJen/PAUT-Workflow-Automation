"""
L0 - decoding: each .nde file read by the Analysis page (analysis.services.nde_data) and by the
independent reference reader (validation.reference), compared. Samples, status bits and axes must agree
exactly; the scale to % of full screen within float32 rounding. Frames compared: the first, middle and
last scan positions and two more picked from the file's fingerprint (the same ones every run).
"""
import hashlib
import os
import random

import numpy as np

from analysis.services import nde_data
from validation import reference

from . import check, item

AGAINST = 'Independent HDF5 reader'
EXACT = 'Exact (bit for bit)'
PERCENT_TOLERANCE = 1e-4   # % - float32 rounding of raw x unitMax / max


def frames_to_compare(count, seed):
    """First, middle, last and two seeded picks (distinct, in order)."""
    picks = {0, count // 2, count - 1}
    rng = random.Random(seed)
    for _ in range(2):
        picks.add(rng.randrange(count))
    return sorted(p for p in picks if 0 <= p < count)


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and float(a) == float(b)
    return a == b


def _fmt(v):
    if isinstance(v, float):
        return f'{v:.9g}'
    return str(v)


# Units the stored values are in, and how they're shown: (label, factor)
UNITS = {'UCoordinate': ('mm', 1e3), 'VCoordinate': ('mm', 1e3), 'Ultrasound': ('µs', 1e6)}


def _shown(value, axis):
    """A stored SI value as shown: in mm / µs, every significant digit kept."""
    unit, factor = UNITS.get(axis, ('', 1))
    return f'{value * factor:.12g} {unit}'.strip() if isinstance(value, (int, float)) else str(value)


def compare_group(path, info, ref, seed):
    """The checks for one group: [check]."""
    title = f"{os.path.basename(path)} · {ref['name'] or ref['id']}"
    app = next((g for g in info.groups if g.id == ref['id']), None)
    if ref['amplitude'] is None:
        reason = app.reason if app else 'no A-scan amplitude dataset'
        return [check('Group without A-scan data', title, AGAINST, [
            item('Shown by the app', 'No (no A-scan amplitude data)', f'No - {reason}', app is None or app.layout == nde_data.UNSUPPORTED, EXACT)],
            note='Listed so nothing is skipped silently: such groups (e.g. TFM) are not shown by the app - use OmniPC.', kind='info')]
    if app is None:
        return [check('Group read', title, AGAINST, [item('Group found by the app', 'Yes', 'No', False, EXACT)])]
    if app.layout == nde_data.UNSUPPORTED:
        return [check('Group the app does not show', title, AGAINST, [item('Shown by the app', 'Not supported', app.reason, True, EXACT)],
                      note='Not shown by the app - use OmniPC for this group.', kind='info')]

    amp = ref['amplitude']
    items = []
    shape = amp['shape'] if len(amp['shape']) == 3 else (amp['shape'][0], 1, amp['shape'][1])
    items.append(item('Data shape (scan x lateral x samples)', ' x '.join(map(str, shape)),
                      ' x '.join(map(str, app.shape)), tuple(app.shape) == tuple(shape), EXACT))

    # Axes: as stored on the dataset (a one-line dataset has no lateral dimension: the app adds one beam)
    stored = reference.dims(ref)
    app_axes = [app.axes[0], app.axes[2]] if app.single else app.axes
    for d, a in zip(stored, app_axes):
        for key in ('quantity', 'offset', 'resolution'):
            if key == 'quantity' and key not in d:
                continue
            if key != 'quantity' and d.get('axis') == 'Beam':
                continue   # beams are listed one by one below, not as a stepped axis
            want = d[key] if key == 'quantity' else (d.get(key, 0.0) or 0.0)
            got = getattr(a, key)
            show = (lambda v: str(v)) if key == 'quantity' else (lambda v: _shown(v, d.get('axis')))
            items.append(item(f"{d.get('axis')} {key}", show(want), show(got), _same(want, got), EXACT))

    # Beams: angles, skews, exit points, velocity and first-sample times as stored per beam
    if app.layout == nde_data.BEAMS and not app.single:
        stored_beams = (stored[1].get('beams') or []) if len(stored) > 1 else []
        items.append(item('Beams', str(len(stored_beams)), str(len(app.beams)), len(stored_beams) == len(app.beams), EXACT))
        bad = []
        for k, (b, a) in enumerate(zip(stored_beams, app.beams)):
            pairs = [('refractedAngle', a.refracted_angle), ('skewAngle', a.skew_angle), ('uCoordinateOffset', a.u_offset),
                     ('vCoordinateOffset', a.v_offset), ('ultrasoundOffset', a.ultrasound_offset)]
            if 'velocity' in b:
                pairs.append(('velocity', a.velocity))
            for key, got in pairs:
                if key in b and not _same(b[key], got):
                    bad.append(f'beam {k} {key}: file {_fmt(b[key])}, app {_fmt(got)}')
        items.append(item('Beam angles, skews, exit points, velocities, start times',
                          f'{len(stored_beams)} beams as stored', 'all equal' if not bad else '; '.join(bad[:5]), not bad, EXACT))
    elif app.layout == nde_data.RASTER:
        v = stored[1]
        want = [(v.get('offset') or 0.0) + i * (v.get('resolution') or 0.0) for i in range(amp['shape'][1])]
        got = [b.v_offset for b in app.beams]
        ok = len(want) == len(got) and all(_same(x, y) for x, y in zip(want, got))
        items.append(item('Index positions of the A-scan lines', f'{len(want)} from offset + i x resolution',
                          'all equal' if ok else 'differ', ok, EXACT))

    # Gates: as set in the instrument
    stored_gates = ref['process'].get('gates') or []
    items.append(item('Gates', str(len(stored_gates)), str(len(app.gates)), len(stored_gates) == len(app.gates), EXACT))
    for g, a in zip(stored_gates, app.gates):
        start = g.get('start', (g.get('starts') or [0.0])[0])
        length = g.get('length', (g.get('lengths') or [0.0])[0])
        ok = g.get('name', a.name) == a.name and _same(float(g.get('threshold', 0.0)), float(a.threshold)) \
            and _same(float(start), float(a.start)) and _same(float(length), float(a.length))
        name = g.get('name') or a.name
        items.append(item(f"{name if name.lower().startswith('gate') else 'Gate ' + name}: start, length, threshold",
                          f"{_shown(float(start), 'Ultrasound')}, {_shown(float(length), 'Ultrasound')}, {_fmt(float(g.get('threshold', 0.0)))} %",
                          f"{_shown(a.start, 'Ultrasound')}, {_shown(a.length, 'Ultrasound')}, {_fmt(a.threshold)} %", ok, EXACT))

    # Scale to % of full screen
    value = amp['value']
    items.append(item('Full scale (raw max -> unit max)', f"{value.get('max')} -> {value.get('unitMax')} {value.get('unit', '')}",
                      f'{app.raw_max} -> {app.unit_max} {app.unit}',
                      _same(value.get('max'), app.raw_max) and _same(float(value.get('unitMax')), float(app.unit_max)), EXACT))

    # Samples, status and % at the chosen frames
    frames = frames_to_compare(shape[0], seed)
    compared = differ = status_differ = 0
    worst_percent = 0.0
    first_bad = ''
    for s in frames:
        want = reference.frame(path, ref, s)
        got, got_status = nde_data.read_frame(path, app, s)
        if want.shape != got.shape:
            differ += want.size
            first_bad = first_bad or f'scan {s}: shape {want.shape} vs {got.shape}'
            continue
        diff = want.astype(np.int64) != got.astype(np.int64)
        compared += want.size
        if diff.any():
            differ += int(diff.sum())
            lateral, sample = map(int, np.argwhere(diff)[0])
            first_bad = first_bad or f'scan {s}, line {lateral}, sample {sample}: file {want[lateral, sample]}, app {got[lateral, sample]}'
        worst_percent = max(worst_percent, float(np.max(np.abs(reference.percent(want, ref) - nde_data.to_unit(got, app)))))
        want_status = reference.status(path, ref, s)
        if want_status is not None and (got_status is None or not np.array_equal(want_status, got_status)):
            status_differ += 1
        # One A-scan read on its own as well (what the A-scan view and readings use)
        lateral = random.Random(seed + s).randrange(want.shape[0])
        if not np.array_equal(nde_data.read_ascan(path, app, s, lateral).astype(np.int64), want[lateral].astype(np.int64)):
            differ += 1
            first_bad = first_bad or f'scan {s}, line {lateral}: the A-scan read alone differs'
    items.append(item(f"Raw samples at scan positions {', '.join(map(str, frames))}",
                      f'{compared:,} samples ({amp["dtype"]})', f'{differ:,} differ' + (f' - first at {first_bad}' if first_bad else ''),
                      differ == 0 and compared > 0, EXACT))
    if ref['status']:
        items.append(item('A-scan status bits (has data / saturated / no synchro)', f'{len(frames)} frames',
                          f'{status_differ} differ', status_differ == 0, EXACT))
    items.append(item('Amplitude in % of full screen', 'raw x unitMax / max (double precision)', f'largest difference {worst_percent:.2g} %',
                      worst_percent <= PERCENT_TOLERANCE, f'Within {PERCENT_TOLERANCE} % (float32 rounding)'))
    return [check('Decoding', title, AGAINST, items)]


def check_file(path, seed=None):
    """All the checks for one file."""
    if seed is None:
        seed = int(hashlib.sha256(os.path.abspath(path).lower().encode()).hexdigest()[:8], 16)
    title = os.path.basename(path)
    try:
        info = nde_data.open_file(path)
    except nde_data.NdeDataError as e:
        return [check('Decoding', title, AGAINST, [item('Opened by the app', 'Yes', f'No - {e}', False, EXACT)])]
    try:
        groups = reference.groups(path)
    except Exception as e:   # the reference couldn't read it: say so, it isn't a pass
        return [check('Decoding', title, AGAINST, [item('Read by the reference reader', 'Yes', f'No - {e}', False, EXACT)])]
    out = []
    for ref in groups:
        out += compare_group(path, info, ref, seed)
    return out


def run(context):
    files = [(context.kit.full_path(e), int(e['sha256'][:8], 16)) for e in context.files if e['path'].lower().endswith('.nde')]
    sweep = []
    if context.options.get('sweep'):
        listed = {os.path.normcase(p) for p, _ in files}
        for root, _, names in os.walk(context.options['sweep']):
            for name in sorted(names):
                full = os.path.join(root, name)
                if name.lower().endswith('.nde') and os.path.normcase(full) not in listed:
                    sweep.append((full, None))
    todo = files + sweep
    if not todo:
        context.message('No .nde files in the kit.')
    for n, (path, seed) in enumerate(todo):
        if context.cancelled():
            return
        context.progress(f'Reading {os.path.basename(path)}', n / max(1, len(todo)))
        for c in check_file(path, seed):
            if seed is None:
                c['note'] = (c['note'] + ' ' if c['note'] else '') + 'Archive sweep: not in the kit, not fingerprinted.'
                folder = os.path.relpath(os.path.dirname(path), context.options['sweep'])
                c['subject'] = c['subject'] if folder == '.' else f"{folder}{os.sep}{c['subject']}"
            context.emit(c)
