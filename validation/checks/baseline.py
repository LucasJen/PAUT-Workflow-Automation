"""
L6 - baseline: what the app computes on the kit's .nde files, locked when it was approved, compared
with what it computes now. Locked (kit baseline/, fingerprinted like the rest of the kit):
    - the readings the page shows (edge and peak) on a grid of A-scans: 5 scan positions x 3 lines
    - every C-scan array (amplitudes, positions, thicknesses per gate) in full
    - every indication Find indications finds in gate A (its default settings), with its sizing
Any change - a code change, a library update - shows here until it's explained and the baseline is
approved again (a run with 'approve' locks the current results, with a note of who and why).
"""
import datetime
import json
import math
import os
import shutil
import tempfile
from dataclasses import replace

import numpy as np
from django.conf import settings
from django.test import RequestFactory, override_settings

from analysis.services import detection, nde_data, projections

from . import check, item
from .readings import page_readings

AGAINST = 'The approved baseline'
FOLDER = 'baseline'
INDEX = 'baseline.json'


def _grid(n, picks):
    return sorted({min(n - 1, max(0, round(f * (n - 1)))) for f in picks})


def _clean(value):
    """JSON-safe: floats kept to 12 significant digits (the float32 C-scans and float64 readings agree far
    beyond any displayed digit), NaN / inf as text."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else str(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def capture(path, kit_root, progress=None):
    """
    {group id: {readings, cscan: {name: array}, detection}} - everything the baseline locks for one file.
    The C-scans are built from scratch in a folder of their own, never read from the page's cache.
    """
    info = nde_data.open_file(path)
    factory = RequestFactory()
    out = {}
    scratch = tempfile.mkdtemp(prefix='validation-cscan-')
    try:
        return _capture(path, info, kit_root, factory, scratch, out, progress)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _capture(path, info, kit_root, factory, scratch, out, progress):
    with override_settings(ANALYSIS_EXTRA_ROOTS=list(getattr(settings, 'ANALYSIS_EXTRA_ROOTS', [])) + [kit_root]):
        for group in info.groups:
            if group.layout == nde_data.UNSUPPORTED:
                continue
            gates = group.gates
            readings = {}
            for scan in _grid(group.shape[0], (0, 0.25, 0.5, 0.75, 1)):
                for lateral in _grid(group.shape[1], (0, 0.5, 1)):
                    edge, note = page_readings(factory, path, group.id, scan, lateral, [replace(g, detection='edge') for g in gates])
                    peak, _ = page_readings(factory, path, group.id, scan, lateral, [replace(g, detection='maxpeak') for g in gates])
                    readings[f'{scan},{lateral}'] = _clean({'edge': edge, 'peak': peak, 'note': note})
            if progress:
                progress(f'Building the C-scan of {os.path.basename(path)}')
            projections.build(path, group, gates, 0.0, folder=scratch)
            cscan = dict(projections.read_cscan(path, group, gates, 0.0, folder=scratch) or {})
            found = []
            if 'A_amplitude' in cscan:
                sized, _ = detection.detect(path, info, group, gates, cscan, 'A')
                found = [_clean(s) for s in sized]
            out[group.id] = {'readings': readings, 'cscan': {k: np.asarray(v) for k, v in cscan.items()}, 'detection': found}
    return out


def _stem(entry, gid):
    return f"{os.path.splitext(os.path.basename(entry['path']))[0]} G{gid}"


def lock(context, note):
    """Captures the current results as the approved baseline (replacing any before)."""
    kit = context.kit
    folder = os.path.join(kit.root, FOLDER)
    os.makedirs(folder, exist_ok=True)
    index = {'approved': datetime.datetime.now().isoformat(timespec='seconds'), 'note': note,
             'version': context.run.version if getattr(context, 'run', None) else '', 'files': {}}
    entries = [e for e in context.files if e['path'].lower().endswith('.nde')]
    for n, entry in enumerate(entries):
        context.progress(f"Locking {entry['path']}", n / max(1, len(entries)))
        results = capture(kit.full_path(entry), kit.root, lambda m: context.progress(m, n / max(1, len(entries))))
        groups = {}
        for gid, r in results.items():
            arrays = os.path.join(folder, f'{_stem(entry, gid)} cscan.npz')
            np.savez_compressed(arrays, **r['cscan'])
            kit.add(arrays, ['baseline'], 'Locked by validation', note)
            groups[str(gid)] = {'readings': r['readings'], 'detection': r['detection'],
                                'cscan': os.path.relpath(arrays, kit.root).replace(os.sep, '/'), 'sha256': entry['sha256']}
            context.emit(check('Locked', f"{os.path.basename(entry['path'])} · group {gid}", AGAINST, [
                item('Readings locked', '', f"{len(r['readings'])} A-scans", None, 'Locked'),
                item('C-scan arrays locked', '', ', '.join(sorted(r['cscan'])) or 'none', None, 'Locked'),
                item('Indications found', '', str(len(r['detection'])), None, 'Locked')], kind='info'))
        index['files'][entry['path']] = groups
    path = os.path.join(folder, INDEX)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=1)
    kit.add(path, ['baseline'], 'Locked by validation', note)
    context.message(f"Locked as the approved baseline: {note}")


def _array_diff(old, new):
    """('same' | description, ok) for two C-scan arrays."""
    if old.shape != new.shape:
        return f'shape {new.shape}, locked {old.shape}', False
    nan_old, nan_new = np.isnan(old), np.isnan(new)
    if not np.array_equal(nan_old, nan_new):
        return f'{int((nan_old != nan_new).sum())} cells changed between data and no data', False
    both = ~nan_old
    if np.array_equal(old[both], new[both]):
        return 'identical', True
    diff = np.abs(old[both].astype(np.float64) - new[both].astype(np.float64))
    return f'{int((diff > 0).sum())} of {int(both.sum())} cells differ, by up to {diff.max():.3g}', False


def _same_value(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a))
    return a == b


def compare(context):
    kit = context.kit
    index_path = os.path.join(kit.root, FOLDER, INDEX)
    listed = {e['path'] for e in context.files}
    if not os.path.isfile(index_path):
        context.message('No approved baseline yet: approve one to lock the current results.')
        return
    if f'{FOLDER}/{INDEX}' not in listed:
        context.emit(check('Baseline', INDEX, AGAINST, [item('Baseline fingerprint', 'matches', 'changed or not in the kit', False, 'Exact')]))
        return
    with open(index_path, encoding='utf-8') as f:
        index = json.load(f)
    entries = {e['path']: e for e in context.files}
    files = list(index['files'].items())
    for n, (kit_path, groups) in enumerate(files):
        entry = entries.get(kit_path)
        if entry is None:
            context.emit(check('Baseline', kit_path, AGAINST, [item('In the kit', 'yes', 'missing or changed', False, 'Exact')]))
            continue
        context.progress(f'Recomputing {kit_path}', n / max(1, len(files)))
        now = capture(kit.full_path(entry), kit.root, lambda m: context.progress(m, n / max(1, len(files))))
        for gid, locked in groups.items():
            current = now.get(int(gid))
            subject = f'{os.path.basename(kit_path)} · group {gid}'
            if current is None:
                context.emit(check('Baseline', subject, AGAINST, [item('Group read', 'yes', 'no', False, 'Exact')]))
                continue
            items = []
            changed = [k for k, v in locked['readings'].items() if _clean(current['readings'].get(k)) != v
                       and not all(_same_value(a, b) for a, b in _pairs(v, _clean(current['readings'].get(k))))]
            items.append(item('Readings on the A-scan grid', f"{len(locked['readings'])} A-scans",
                              'all the same' if not changed else f"{len(changed)} differ (A-scans {', '.join(changed[:4])})",
                              not changed, 'The same to 1 part in a billion'))
            if f"{FOLDER}/{os.path.basename(locked['cscan'])}" not in listed:
                items.append(item('C-scan arrays', 'locked', 'the locked arrays are missing or changed', False, 'Identical'))
            else:
                with np.load(os.path.join(kit.root, locked['cscan'])) as data:
                    old = {k: data[k] for k in data.files}
                for name in sorted(set(old) | set(current['cscan'])):
                    if name not in current['cscan'] or name not in old:
                        items.append(item(f'C-scan {name}', 'locked' if name in old else 'not locked',
                                          'present' if name in current['cscan'] else 'missing', False, 'Identical'))
                        continue
                    text, ok = _array_diff(old[name], np.asarray(current['cscan'][name]))
                    items.append(item(f'C-scan {name}', f'{old[name].shape[0]} x {old[name].shape[1]} cells', text, ok, 'Identical, cell for cell'))
            was, found = locked['detection'], current['detection']
            same = len(was) == len(found) and all(all(_same_value(a.get(k), b.get(k)) for k in set(a) | set(b)) for a, b in zip(was, found))
            items.append(item('Indications found and sized (gate A)', f'{len(was)} indications', f'{len(found)} indications' + ('' if same else ', changed'),
                              same, 'The same indications, sized the same'))
            context.emit(check('Baseline', subject, AGAINST, items, note=f"Approved {index['approved']}: {index.get('note', '')}"))


def _pairs(a, b):
    """Leaf value pairs of two JSON structures of the same shape (unequal shapes give a mismatched pair)."""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            yield a, b
            return
        for k in a:
            yield from _pairs(a[k], b[k])
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield a, b
            return
        for x, y in zip(a, b):
            yield from _pairs(x, y)
    else:
        yield a, b


def run(context):
    note = context.options.get('approve')
    if note:
        lock(context, note)
    else:
        compare(context)
