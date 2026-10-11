"""
Finding indications: every signal in a gate that breaks its threshold, on the cached gate map (the
C-scan in projections.py - amplitude over [scan, line], the gate's highest sample, so "at or above
the threshold" is the same test the readings use for a crossing).

    mask       amplitude >= threshold at each scan position x line
    regions    8-connected cells of the mask (no scipy here: runs of each scan position joined by a
               small union-find)
    merge      two regions whose line spans overlap (or touch) and that are at most `merge_gap` scan
               positions apart are one indication - a flaw that dips under the threshold for a step
    minimums   regions shorter than `min_scans` positions or narrower than `min_lines` lines are dropped

Each indication is then sized (sizing.size_indication): taken to 80 % of full screen, its length by
the dB drop along the scan, its height and axial position by the same drop on the S-scan at its peak.
"""
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


def _region(labels, amplitude, n):
    """Each region's spans and peak, from the labels."""
    regions = []
    for k in range(1, n + 1):
        scans, lines = np.nonzero(labels == k)
        values = amplitude[scans, lines]
        top = int(np.argmax(values))
        regions.append({'scan_lo': int(scans.min()), 'scan_hi': int(scans.max()),
                        'line_lo': int(lines.min()), 'line_hi': int(lines.max()),
                        'peak_scan': int(scans[top]), 'peak_line': int(lines[top]),
                        'peak_amplitude': float(values[top]), 'cells': int(len(values))})
    return regions


def _merged(a, b):
    first = a if a['peak_amplitude'] >= b['peak_amplitude'] else b
    return {'scan_lo': min(a['scan_lo'], b['scan_lo']), 'scan_hi': max(a['scan_hi'], b['scan_hi']),
            'line_lo': min(a['line_lo'], b['line_lo']), 'line_hi': max(a['line_hi'], b['line_hi']),
            'peak_scan': first['peak_scan'], 'peak_line': first['peak_line'],
            'peak_amplitude': first['peak_amplitude'], 'cells': a['cells'] + b['cells']}


def merge(regions, gap):
    """Regions joined while two overlap in lines (or touch) and are at most `gap` scan positions apart."""
    regions = list(regions)
    changed = True
    while changed:
        changed = False
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                a, b = regions[i], regions[j]
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


def find_regions(amplitude, threshold, merge_gap=2, min_scans=1, min_lines=1):
    """
    The indications on a gate map (amplitude [scans, lines], NaN = nothing): a dict each with its scan
    and line spans, its peak cell and amplitude, in scan order.
    """
    a = np.where(np.isnan(amplitude), -np.inf, np.asarray(amplitude, dtype=np.float64))
    labels, n = label(a >= threshold)
    regions = merge(_region(labels, a, n), max(0, int(merge_gap)))
    regions = [r for r in regions if r['scan_hi'] - r['scan_lo'] + 1 >= min_scans
               and r['line_hi'] - r['line_lo'] + 1 >= min_lines]
    return sorted(regions, key=lambda r: (r['scan_lo'], r['line_lo']))
