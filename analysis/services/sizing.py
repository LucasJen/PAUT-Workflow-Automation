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
import numpy as np

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
