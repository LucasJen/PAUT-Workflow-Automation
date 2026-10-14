"""
Indication sizing on the gate maps (the C-scan data in projections.py, so the same gate rules as the
readings): the length of an indication along the scan axis (or its width along a raster's index
axis) by an amplitude drop from its peak - -6 dB (half the peak), -12 dB, -20 dB - or down to the
gate's threshold.

    profile    the gate's amplitude along the axis at the cursor's line (or the most of all the lines
               at each position - the projection a sectorial scan is usually sized on)
    peak       from the cursor, climb to the highest point of the indication; the level is the peak
               less the drop (or the threshold); if a higher point turns up inside that span, it
               becomes the peak and the span is worked out again
    ends       where the profile crosses the level on each side, interpolated between the two
               positions either side of the crossing (or the edge of the data)
"""
import math

import numpy as np

from .geometry import fold_depth, position
from .nde_data import read_frame, to_unit
from .readings import evaluate_gates, peak_position

FULL_SCREEN_TARGET = 80.0   # % - each indication is taken to this before it's sized
SATURATED_SHARE = 0.99      # a peak sample this close to the raw maximum is clipped
METHODS = {'6': 6.0, '12': 12.0, '20': 20.0}


class SizingError(Exception):
    pass


def profile(amplitude, axis, line, scan, lines='current'):
    """The amplitude profile to size along: amplitude is [scans, lines] (NaN = nothing)."""
    a = np.where(np.isnan(amplitude), 0.0, amplitude)
    if axis == 'index':
        return a[scan, :]
    if lines == 'all':
        return a.max(axis=1)
    if isinstance(lines, (tuple, list)):   # the most of a span of lines (an indication's own)
        lo, hi = max(0, int(lines[0])), min(a.shape[1] - 1, int(lines[1]))
        return a[:, lo:hi + 1].max(axis=1)
    return a[:, line]


def size(values, cursor, drop_db=6.0, threshold=None):
    """
    {'peak', 'peak_amplitude', 'level', 'start', 'end'} for the indication at `cursor` on a profile;
    peak is an index, start / end fractional indices of the level crossings.
    """
    v = np.asarray(values, dtype=np.float64)
    n = len(v)
    if not 0 <= cursor < n:
        raise SizingError('The cursor is outside the data.')
    p = int(cursor)
    while True:   # climb to the top of the hill the cursor is on
        better = [i for i in (p - 1, p + 1) if 0 <= i < n and v[i] > v[p]]
        if not better:
            break
        p = max(better, key=lambda i: v[i])
    if v[p] <= 0:
        raise SizingError('No signal in the gate at the cursor.')
    for _ in range(10):
        level = threshold if threshold is not None else v[p] * 10 ** (-drop_db / 20)
        if v[p] < level:
            raise SizingError('The peak is below the gate threshold.')
        left = p
        while left > 0 and v[left - 1] >= level:
            left -= 1
        right = p
        while right < n - 1 and v[right + 1] >= level:
            right += 1
        top = left + int(np.argmax(v[left:right + 1]))
        if v[top] <= v[p]:
            break
        p = top
    start = left - (v[left] - level) / (v[left] - v[left - 1]) if left > 0 and v[left] != v[left - 1] else float(left)
    end = right + (v[right] - level) / (v[right] - v[right + 1]) if right < n - 1 and v[right] != v[right + 1] else float(right)
    return {'peak': p, 'peak_amplitude': float(v[p]), 'level': float(level), 'start': float(start), 'end': float(end)}


def size_length(cscan, group, gate_letter, scan, line, axis='scan', lines='current', method='6', threshold=None):
    """
    Sizing on the cached gate map, in metres along the axis: {'start', 'end', 'length', 'peak_position',
    'peak_amplitude', 'level', 'method', 'axis', 'peak_index'}.
    """
    key = f'{gate_letter}_amplitude'
    if key not in cscan:
        raise SizingError(f'There is no gate {gate_letter}.')
    if axis == 'index' and group.layout != 'raster':
        raise SizingError('Width along the index axis is for raster scans; use the scan axis.')
    values = profile(cscan[key], axis, line, scan, lines)
    cursor = line if axis == 'index' else scan
    if method == 'threshold':
        result = size(values, cursor, threshold=threshold)
    elif method in METHODS:
        result = size(values, cursor, drop_db=METHODS[method])
    else:
        raise SizingError('Unknown sizing method.')
    ax = group.axes[1] if axis == 'index' else group.axes[0]
    to_m = lambda i: ax.offset + i * ax.resolution
    start, end = to_m(result['start']), to_m(result['end'])
    return {'start': start, 'end': end, 'length': abs(end - start), 'peak_position': to_m(result['peak']),
            'peak_index': result['peak'], 'peak_amplitude': result['peak_amplitude'], 'level': result['level'],
            'method': method, 'axis': axis}


# ── an indication found by detection.py, sized as a whole ──────────────

def gain_to_target(peak, target=FULL_SCREEN_TARGET):
    """dB that takes a peak of `peak` % to the target (80 % of full screen): + more gain, - less."""
    if not peak or peak <= 0:
        return 0.0
    return 20 * math.log10(target / peak)


def drop_db(method):
    if method not in METHODS:
        raise SizingError('Unknown sizing method.')
    return METHODS[method]


def _grow(values, start, level):
    """Cells of the 8-connected region of values >= level around `start` (values [rows, cols])."""
    rows, cols = values.shape
    seen = np.zeros(values.shape, dtype=bool)
    seen[start] = True
    todo, cells = [start], []
    while todo:
        r, c = todo.pop()
        cells.append((r, c))
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols and not seen[rr, cc] and values[rr, cc] >= level:
                    seen[rr, cc] = True
                    todo.append((rr, cc))
    return cells


def frame_extent(path, info, group, gates, letter, scan, line, drop, gain=0.0):
    """
    Height and axial extent of the indication on the S-scan at scan position `scan`: the region around
    the gate's peak on `line` that stays at or above the peak less `drop` dB, inside the gate on every
    beam. Depths are folded at the back wall; axial positions are PA^ (from the probe's index offset,
    OmniPC's Index). Returns {'peak_sample', 'peak_raw', 'saturated', 'peak_amplitude', 'sound_path',
    'depth', 'leg', 'axial', 'top', 'bottom', 'height', 'axial_start', 'axial_end', 'cells'}.
    """
    raw, _ = read_frame(path, group, scan)
    amplitudes = to_unit(raw, group).astype(np.float64) * 10 ** (gain / 20)
    inside = np.zeros(amplitudes.shape, dtype=bool)
    period = group.ultrasound_axis.resolution
    for b, beam in enumerate(group.beams[:amplitudes.shape[0]]):
        result = evaluate_gates(group, beam, raw[b], gates).get(letter)
        if result is None or not result.found or result.start is None:
            continue
        times = beam.ultrasound_offset + np.arange(amplitudes.shape[1]) * period
        inside[b] = (times >= result.start) & (times <= result.end)
    if not 0 <= line < len(inside) or not inside[line].any():
        raise SizingError(f'Gate {letter} is not on that beam at the peak.')
    gated = np.where(inside, amplitudes, -np.inf)
    sample = int(np.argmax(gated[line]))
    peak = float(gated[line, sample])
    if peak <= 0:
        raise SizingError('No signal in the gate at the peak.')
    cells = _grow(gated, (line, sample), peak * 10 ** (-drop / 20))
    thickness = info.specimen.get('thickness')
    probe = info.probe.get('v_offset', 0.0)
    depths, unfolded, axials = [], [], []
    for b, i in cells:
        _, v, depth = position(group, group.beams[b], i)
        unfolded.append(depth)
        depths.append(fold_depth(depth, thickness)[0])
        axials.append(v - probe)
    beam = group.beams[line]
    sp, depth, leg, index = peak_position(beam, beam.ultrasound_offset + sample * period, thickness)
    peak_raw = int(raw[line, sample])
    # At the top of the digitizer's range (the files' own saturated status bit is set on every A-scan
    # with data in the user's files, so it can't say which peak is clipped)
    saturated = peak_raw >= SATURATED_SHARE * group.raw_max
    return {'peak_sample': sample, 'peak_raw': peak_raw, 'saturated': saturated, 'peak_amplitude': peak,
            'sound_path': sp, 'depth': depth, 'leg': leg, 'axial': index - probe,
            'top': min(depths), 'bottom': max(depths), 'height': max(depths) - min(depths),
            'axial_start': min(axials), 'axial_end': max(axials), 'cells': len(cells),
            # Where it is on the S-scan and B-scan, which draw depth unfolded (leg 2 below the back wall)
            'view_top': min(unfolded), 'view_bottom': max(unfolded)}


def size_indication(path, info, group, gates, cscan, letter, region, method='6', gain=0.0):
    """
    An indication sized as the technique has it: its gain to 80 % of full screen from its peak, its
    length along the scan by the dB drop on the most of its own lines, and (on a weld's beams) its
    height, depth and axial position by the same drop on the S-scan at its peak. A raster scan has a
    width along the index axis instead of a height. Lengths in m.

    The dB drop is relative to the peak, so taking it to 80 % sets the reference without moving the
    ends - except on a saturated peak, whose true amplitude (and so its drop level) can't be known:
    that is flagged.
    """
    drop = drop_db(method)
    key = f'{letter}_amplitude'
    if key not in cscan:
        raise SizingError(f'There is no gate {letter}.')
    amplitude = cscan[key]
    scan_axis, line_axis = group.axes[0], group.axes[1]
    to_scan = lambda i: scan_axis.offset + i * scan_axis.resolution
    peak_line = region['peak_line']
    span = (region['line_lo'] - 1, region['line_hi'] + 1)
    length = size(profile(amplitude, 'scan', peak_line, region['peak_scan'], span), region['peak_scan'], drop_db=drop)
    peak_scan = length['peak']   # the length's own peak (it can climb past the region's)
    ends = sorted((to_scan(length['start']), to_scan(length['end'])))
    result = {
        'auto': True, 'method': method, 'gate': letter, 'base_gain': gain,
        'scan_start': ends[0], 'scan_end': ends[1], 'length': ends[1] - ends[0],
        'scan_position': to_scan(peak_scan), 'peak_scan': peak_scan,
        'line_lo': region['line_lo'], 'line_hi': region['line_hi'],
    }
    if group.layout == 'raster':
        width = size(profile(amplitude, 'index', peak_line, peak_scan), peak_line, drop_db=drop)
        to_index = lambda i: line_axis.offset + i * line_axis.resolution
        sides = sorted((to_index(width['start']), to_index(width['end'])))
        peak_line = width['peak']
        result.update({'axial_start': sides[0], 'axial_end': sides[1], 'width': sides[1] - sides[0],
                       'axial': to_index(peak_line)})
    frame = frame_extent(path, info, group, gates, letter, peak_scan, peak_line, drop, gain)
    result.update({
        'peak_line': peak_line, 'peak_sample': frame['peak_sample'],
        # % at the file's gain plus the soft gain it was found at (base_gain); base_gain + gain_db shows it at 80 %
        'peak_amplitude': frame['peak_amplitude'], 'gain_db': gain_to_target(frame['peak_amplitude']),
        'saturated': frame['saturated'], 'sound_path': frame['sound_path'],
        'peak_depth': frame['depth'], 'leg': frame['leg'], 'angle': group.beams[peak_line].refracted_angle,
    })
    if group.layout == 'raster':
        result['depth'] = frame['depth']
    else:
        result.update({'depth': frame['top'], 'height': frame['height'], 'top': frame['top'],
                       'bottom': frame['bottom'], 'view_top': frame['view_top'], 'view_bottom': frame['view_bottom'],
                       'thickness': info.specimen.get('thickness'), 'axial': frame['axial'],
                       'axial_start': frame['axial_start'], 'axial_end': frame['axial_end']})
    return result


def size_in_box(path, info, group, gates, cscan, letter, box, method='6', gain=0.0):
    """
    Contour sizing (UltraVision's Dropsizing): the strongest signal inside a box drawn on the C-scan -
    box = (scan_lo, scan_hi, line_lo, line_hi), C-scan cells - sized as a found indication is (length
    by the dB drop over the box's lines, height / depth / axial extent on the S-scan at its peak), but
    nothing outside the box counts: the ends stop at its sides.
    """
    key = f'{letter}_amplitude'
    if key not in cscan:
        raise SizingError(f'There is no gate {letter}.')
    amplitude = cscan[key]
    scans, lines = amplitude.shape
    s0, s1 = sorted((max(0, min(scans - 1, int(box[0]))), max(0, min(scans - 1, int(box[1])))))
    l0, l1 = sorted((max(0, min(lines - 1, int(box[2]))), max(0, min(lines - 1, int(box[3])))))
    inside = np.full(amplitude.shape, np.nan)
    inside[s0:s1 + 1, l0:l1 + 1] = amplitude[s0:s1 + 1, l0:l1 + 1]
    cells = np.nan_to_num(inside, nan=-1.0)
    peak_scan, peak_line = np.unravel_index(int(np.argmax(cells)), cells.shape)
    if cells[peak_scan, peak_line] <= 0:
        raise SizingError(f'No gate {letter} signal inside the box.')
    region = {'peak_scan': int(peak_scan), 'peak_line': int(peak_line), 'line_lo': l0 + 1, 'line_hi': l1 - 1}
    result = size_indication(path, info, group, gates, {key: inside}, letter, region, method, gain)
    scan_axis, line_axis = group.axes[0], group.axes[1]
    edge = lambda ax, i, side: ax.offset + (i + side * 0.5) * ax.resolution   # a cell's outer side
    lo, hi = edge(scan_axis, s0, -1), edge(scan_axis, s1, 1)
    result['scan_start'], result['scan_end'] = max(result['scan_start'], lo), min(result['scan_end'], hi)
    result['length'] = result['scan_end'] - result['scan_start']
    if group.layout == 'raster':
        a, b = edge(line_axis, l0, -1), edge(line_axis, l1, 1)
        result['axial_start'], result['axial_end'] = max(result['axial_start'], a), min(result['axial_end'], b)
        result['width'] = result['axial_end'] - result['axial_start']
    result.update({'auto': False, 'contour': True, 'axis': 'scan', 'box': [s0, s1, l0, l1]})
    return result


def folded_span(top, bottom, thickness):
    """(shallowest, deepest) true depth of an unfolded depth span (as drawn on the S-scan) in a part `thickness` thick."""
    a, b = sorted((top, bottom))
    if not thickness or thickness <= 0:
        return a, b
    points = [a, b] + [k * thickness for k in range(int(a // thickness) + 1, int(b // thickness) + 1)]
    depths = [fold_depth(p, thickness)[0] for p in points]
    return min(depths), max(depths)
