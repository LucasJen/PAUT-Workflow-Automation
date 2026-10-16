"""
Finding indications: every signal in a gate that breaks its threshold, on the cached gate map (the
C-scan in projections.py - amplitude over [scan, line], the gate's highest sample, so "at or above
the threshold" is the same test the readings use for a crossing).

    mask       amplitude >= threshold at each scan position x line
    regions    8-connected cells of the mask (no scipy here: runs of each scan position joined by a
               small union-find)
    split      a region with several peaks is several indications: walking down from the highest cell
               (a watershed), a peak whose signal falls at least `split_db` (the sizing drop) before it
               meets a stronger one's area is its own indication, with the cells around it; lesser bumps
               stay with the peak above them. Without this a long run of signal over the threshold (a
               weld root, a scan's worth of geometry) hid every indication in it but the strongest
    merge      two regions whose line spans overlap (or touch) and that are at most `merge_gap` scan
               positions apart are one indication - a flaw that dips under the threshold for a step
               (pieces split from the same region aren't joined again)
    minimums   regions shorter than `min_scans` positions or narrower than `min_lines` lines are dropped

Each indication is then sized (sizing.size_indication): taken to 80 % of full screen, its length by
the dB drop along the scan, its height and axial position by the same drop on the S-scan at its peak.
"""
import math

import numpy as np


class _Union:
    def __init__(self):
        self.parent = []

    def add(self):
        self.parent.append(len(self.parent))
        return len(self.parent) - 1

    def find(self, a):
        root = a
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[a] != root:
            self.parent[a], a = root, self.parent[a]
        return root

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def _runs(row):
    """(start, end) of each run of True in a 1-D bool array, end inclusive."""
    padded = np.concatenate(([False], row, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[::2], edges[1::2] - 1))


def label(mask):
    """(labels int32 [scans, lines] with 0 = background and regions 1..n, n): 8-connected regions."""
    mask = np.asarray(mask, dtype=bool)
    labels = np.zeros(mask.shape, dtype=np.int32)
    union = _Union()
    previous = []   # (start, end, run id) on the scan position before
    runs = []       # (scan, start, end, run id)
    for scan in range(mask.shape[0]):
        current = []
        for start, end in _runs(mask[scan]):
            run = union.add()
            for p_start, p_end, p_run in previous:   # diagonal neighbours count: spans within one line
                if p_start <= end + 1 and start <= p_end + 1:
                    union.join(run, p_run)
            current.append((start, end, run))
            runs.append((scan, start, end, run))
        previous = current
    ids = {}
    for scan, start, end, run in runs:
        root = union.find(run)
        labels[scan, start:end + 1] = ids.setdefault(root, len(ids) + 1)
    return labels, len(ids)


def _bounds(scans, lines, values, blob):
    top = int(np.argmax(values))
    return {'scan_lo': int(scans.min()), 'scan_hi': int(scans.max()),
            'line_lo': int(lines.min()), 'line_hi': int(lines.max()),
            'peak_scan': int(scans[top]), 'peak_line': int(lines[top]),
            'peak_amplitude': float(values[top]), 'cells': int(len(values)), 'blobs': {blob}}


def _region(labels, amplitude, n, split_db=None):
    """Each region's spans and peak, from the labels - split into its separate peaks (split_db)."""
    regions = []
    for k in range(1, n + 1):
        scans, lines = np.nonzero(labels == k)
        values = amplitude[scans, lines]
        if split_db and len(values) > 1:
            for part in _split(scans, lines, values, split_db):
                regions.append(_bounds(scans[part], lines[part], values[part], k))
        else:
            regions.append(_bounds(scans, lines, values, k))
    return regions


def _split(scans, lines, values, drop_db):
    """
    The separate peaks of one region (cells scans / lines / values): index arrays of each one's cells.
    Cells taken highest first; one touching two areas is the saddle between them, where the lower
    area's peak counts as its own indication when it stands `drop_db` or more above the saddle (and is
    kept as it is from then on), else the lower area joins the higher.
    """
    order = np.argsort(-values, kind='stable')
    where = {(int(sc), int(ln)): i for i, (sc, ln) in enumerate(zip(scans, lines))}
    parent, peak, kept, area_of = [], [], set(), {}
    ratio = 10 ** (drop_db / 20)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in order:
        sc, ln = int(scans[i]), int(lines[i])
        roots = {find(area_of[j]) for ds in (-1, 0, 1) for dl in (-1, 0, 1)
                 if (j := where.get((sc + ds, ln + dl))) is not None and j in area_of}
        if not roots:   # a new peak
            parent.append(len(parent))
            peak.append(values[i])
            area_of[i] = len(parent) - 1
            continue
        # The highest-peaked area takes this cell; the others meet it here (the saddle)
        best = max(roots, key=lambda r: peak[r])
        for r in roots - {best}:
            if r in kept:
                continue
            if peak[r] >= values[i] * ratio:   # stands out by the drop: its own indication
                kept.add(r)
            else:
                parent[r] = best
        area_of[i] = best
    parts = {}
    for i, area in area_of.items():
        parts.setdefault(find(area), []).append(i)
    return [np.array(sorted(cells)) for cells in parts.values()]


def _merged(a, b):
    first = a if a['peak_amplitude'] >= b['peak_amplitude'] else b
    return {'scan_lo': min(a['scan_lo'], b['scan_lo']), 'scan_hi': max(a['scan_hi'], b['scan_hi']),
            'line_lo': min(a['line_lo'], b['line_lo']), 'line_hi': max(a['line_hi'], b['line_hi']),
            'peak_scan': first['peak_scan'], 'peak_line': first['peak_line'],
            'peak_amplitude': first['peak_amplitude'], 'cells': a['cells'] + b['cells'],
            'blobs': set(a.get('blobs') or ()) | set(b.get('blobs') or ())}


def merge(regions, gap):
    """Regions joined while two overlap in lines (or touch) and are at most `gap` scan positions apart."""
    regions = list(regions)
    changed = True
    while changed:
        changed = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i], regions[j]
                if (a.get('blobs') or set()) & (b.get('blobs') or set()):
                    continue   # pieces split from the same region stay apart
                lines_meet = a['line_lo'] <= b['line_hi'] + 1 and b['line_lo'] <= a['line_hi'] + 1
                apart = max(a['scan_lo'], b['scan_lo']) - min(a['scan_hi'], b['scan_hi']) - 1
                if lines_meet and apart <= gap:
                    regions[i] = _merged(a, b)
                    del regions[j]
                    changed = True
                    break
            if changed:
                break
    return regions


def find_regions(amplitude, threshold, merge_gap=2, min_scans=1, min_lines=1, split_db=6.0):
    """
    The indications on a gate map (amplitude [scans, lines], NaN = nothing): a dict each with its scan
    and line spans, its peak cell and amplitude, in scan order. split_db: a region's peaks standing that
    far above the signal between them are separate indications (None: one per region).
    """
    a = np.where(np.isnan(amplitude), -np.inf, np.asarray(amplitude, dtype=np.float64))
    labels, n = label(a >= threshold)
    regions = merge(_region(labels, a, n, split_db), max(0, int(merge_gap)))
    regions = [r for r in regions if r['scan_hi'] - r['scan_lo'] + 1 >= min_scans
               and r['line_hi'] - r['line_lo'] + 1 >= min_lines]
    return sorted(regions, key=lambda r: (r['scan_lo'], r['line_lo']))


def readings_of(sized):
    """The OmniPC readings an auto-sized indication carries (for the CSV and the indication table)."""
    names = {'A%': 'peak_amplitude', 'SA^': 'sound_path', 'DA^': 'peak_depth', 'PA^': 'axial',
             'Length': 'length', 'Height': 'height', 'Width': 'width'}
    return {name: sized[key] for name, key in names.items() if sized.get(key) is not None}


def _span(item):
    """(scan lo, scan hi, line lo, line hi) an indication covers, in data positions."""
    s = item.sizing or {}
    if s.get('auto') and 'line_lo' in s:
        return s.get('scan_lo', item.scan), s.get('scan_hi', item.scan), s['line_lo'], s['line_hi']
    return item.scan, item.scan, item.lateral, item.lateral


def overlaps(region, item):
    lo, hi, line_lo, line_hi = _span(item)
    return (region['scan_lo'] <= hi and lo <= region['scan_hi']
            and region['line_lo'] <= line_hi and line_lo <= region['line_hi'])


def detect(path, info, group, gates, cscan, letter, threshold=None, method='6', gain=0.0,
           merge_gap=2, min_length=0.0, min_lines=1):
    """
    (sized, skipped): each indication found in gate `letter` sized (sizing.size_indication, with its
    region's spans as scan_lo / scan_hi), and the regions that couldn't be sized with why. The
    threshold defaults to the gate's own; min_length is in m along the scan.
    """
    from .sizing import SizingError, size_indication
    key = f'{letter}_amplitude'
    if key not in cscan:
        raise ValueError(f'There is no gate {letter}.')
    gate = next((g for g in gates if g.name.strip().split()[-1].upper() == letter), None)
    if threshold is None:
        threshold = gate.threshold if gate else 20.0
    step = abs(group.axes[0].resolution) or 1.0
    min_scans = max(1, int(math.ceil(min_length / step - 1e-9))) if min_length else 1
    # Peaks standing the sizing drop apart are separate indications (6 dB for threshold sizing)
    split_db = float(method) if str(method).replace('.', '', 1).isdigit() else 6.0
    regions = find_regions(cscan[key], threshold, merge_gap, min_scans, min_lines, split_db)
    while True:
        sized, skipped = [], []
        for region in regions:
            try:
                result = size_indication(path, info, group, gates, cscan, letter, region, method, gain)
            except SizingError as e:
                skipped.append({'region': region, 'error': str(e)})
                continue
            result.update({'scan_lo': region['scan_lo'], 'scan_hi': region['scan_hi'], 'detect_threshold': threshold})
            sized.append((region, result))
        # Two regions whose sized lengths overlap on lines that meet are one indication (a weaker part
        # beside a stronger one climbs to the same peak): joined, and sized again as one
        pair = next(((a, b) for i, a in enumerate(sized) for b in sized[i + 1:] if _same(a, b)), None)
        if pair is None:
            return sorted((result for _, result in sized), key=lambda r: (r['scan_start'], r['line_lo'])), skipped
        (ra, _), (rb, _) = pair
        regions = [r for r in regions if r is not ra and r is not rb] + [_merged(ra, rb)]


def _same(a, b):
    (ra, sa), (rb, sb) = a, b
    lines_meet = ra['line_lo'] <= rb['line_hi'] + 1 and rb['line_lo'] <= ra['line_hi'] + 1
    return lines_meet and sa['scan_start'] <= sb['scan_end'] and sb['scan_start'] <= sa['scan_end']
