"""
Views that need the whole file - the C-scan (scan x line, a gate's amplitude / depth / thickness)
and the B-scan (scan x depth for one beam or index line) - built once by streaming the file a few
scan lines at a time, and cached on disk in outputs/analysis_cache/<file key>/:

    g<group>_volume.npy + .json  amplitudes max-pooled to at most MAX_BINS depth bins, uint8
                                 (0-255 = 0-VOLUME_FULL %), stored line-major so one line's B-scan
                                 is one contiguous read
    g<group>_cscan_<gates key>.npz  per gate letter: amplitude (%), peak time and crossing time (s)
                                 at every scan position x line, NaN where the gate found nothing

Gate results follow services/readings.py exactly (checked against OmniPC): crossings are the first
whole sample at or above the threshold, amplitude the highest sample in the gate, GateRelative gates
start from their sync gate's crossing, and an A-scan re-timed to the interface starts at gate I.
Builds run in a background thread; the page polls their progress. Only a block of about BLOCK_SAMPLES
samples is in memory at a time.
"""
import hashlib
import json
import math
import os
import shutil
import threading
import time
from dataclasses import asdict

import h5py
import numpy as np
from django.conf import settings

from .nde_data import open_file
from .readings import _order, gate_letter

MAX_BINS = 512
VOLUME_FULL = 200.0       # % at uint8 255
BLOCK_SAMPLES = 4_000_000 # samples worked on at a time (~16 MB as float32; a few arrays of that)
KEEP_CACHES = 12          # files whose caches are kept (most recently used)

_jobs = {}                # build key -> {'state', 'progress', 'error', 'started'}
_lock = threading.Lock()


# ── where things go ──────────────────────────────────────────────────────

def cache_root():
    return getattr(settings, 'ANALYSIS_CACHE_DIR', None) or os.path.join(settings.BASE_DIR, 'outputs', 'analysis_cache')


def file_key(path):
    stat = os.stat(path)
    text = f'{os.path.normcase(os.path.realpath(path))}|{stat.st_size}|{stat.st_mtime_ns}'
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def cache_dir(path):
    folder = os.path.join(cache_root(), file_key(path))
    os.makedirs(folder, exist_ok=True)
    os.utime(folder)       # most recently used
    return folder


def gates_key(gates, gain):
    """A short key for a set of gates and a soft gain (the C-scan depends on both)."""
    data = [asdict(g) for g in gates] + [round(float(gain), 3)]
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


def prune(keep=KEEP_CACHES):
    """Deletes the caches of all but the `keep` most recently used files."""
    root = cache_root()
    if not os.path.isdir(root):
        return
    folders = sorted((os.path.join(root, d) for d in os.listdir(root)), key=os.path.getmtime, reverse=True)
    for folder in folders[keep:]:
        shutil.rmtree(folder, ignore_errors=True)


# ── gates over many A-scans at once ─────────────────────────────────────

def line_times(group, count):
    """Sample times (s) of every line: [lines, samples] (each beam has its own A-scan start)."""
    period = group.ultrasound_axis.resolution
    offsets = np.array([b.ultrasound_offset for b in group.beams], dtype=np.float64)
    return offsets[:, None] + np.arange(count)[None, :] * period


def gates_block(group, raw, gates, times, gain=0.0):
    """
    Gate results for every line of one scan position: raw int16 [lines, samples] ->
    {letter: {'found', 'amplitude', 'peak_time', 'crossing_time'}} as arrays over the lines
    (amplitude / times NaN where the gate found nothing). Same rules as readings.evaluate_gates.
    """
    if gain:
        raw = np.clip(np.round(raw.astype(np.float64) * 10 ** (gain / 20)), -32768, 32767).astype(np.int16)
    amplitudes = raw.astype(np.float32) * np.float32(group.unit_max / group.raw_max)
    lines = amplitudes.shape[0]
    results, by_id = {}, {}
    for gate in _order(gates):
        letter = gate_letter(gate.name)
        if gate.sync_mode == 'GateRelative':
            ref = by_id.get(gate.sync_gate)
            if ref is None:
                found = np.zeros(lines, dtype=bool)
                event = np.full(lines, np.nan)
            else:
                event = ref['peak_time'] if gate.trigger == 'MaxPeak' else ref['crossing_time']
                found = ref['found'] & ~np.isnan(event)
            start = np.where(found, event, 0.0) + gate.start
        elif group.synced_to_interface and any(g.sync_gate == gate.id for g in gates):
            zeros = np.zeros(lines)
            by_id[gate.id] = results[letter] = {'found': np.ones(lines, dtype=bool), 'amplitude': np.full(lines, np.nan),
                                                'peak_time': zeros, 'crossing_time': zeros}
            continue
        else:
            found = np.ones(lines, dtype=bool)
            start = np.full(lines, gate.start)
        end = start + gate.length
        inside = (times >= start[:, None]) & (times <= end[:, None]) & found[:, None]
        any_inside = inside.any(axis=1)
        masked = np.where(inside, amplitudes, -np.inf)
        top = np.argmax(masked, axis=1)
        rows = np.arange(lines)
        amplitude = np.where(any_inside, masked[rows, top], np.nan)
        peak_time = np.where(any_inside, times[rows, top], np.nan)
        over = inside & (amplitudes >= gate.threshold)
        crossed = over.any(axis=1)
        first = np.argmax(over, axis=1)
        crossing_time = np.where(crossed, times[rows, first], np.nan)
        by_id[gate.id] = results[letter] = {'found': found, 'amplitude': amplitude, 'peak_time': peak_time,
                                            'crossing_time': crossing_time}
    return results


# ── building ──────────────────────────────────────────────────────────────

def _volume_paths(folder, group_id):
    return os.path.join(folder, f'g{group_id}_volume.npy'), os.path.join(folder, f'g{group_id}_volume.json')


def _cscan_path(folder, group_id, key):
    return os.path.join(folder, f'g{group_id}_cscan_{key}.npz')


def volume_info(path, group):
    """The cached volume's {'lines', 'scans', 'bins', 'factor'} or None when it isn't built."""
    data_path, meta_path = _volume_paths(cache_dir(path), group.id)
    if not (os.path.exists(data_path) and os.path.exists(meta_path)):
        return None
    with open(meta_path, encoding='utf-8') as f:
        return json.load(f)


def build(path, group, gates, gain=0.0, progress=None):
    """
    Builds whatever isn't cached yet for this group: the volume (once per file) and the C-scan for
    these gates and gain. `progress(fraction)` is called as it goes.
    """
    folder = cache_dir(path)
    data_path, meta_path = _volume_paths(folder, group.id)
    cscan_path = _cscan_path(folder, group.id, gates_key(gates, gain))
    need_volume = not (os.path.exists(data_path) and os.path.exists(meta_path))
    need_cscan = not os.path.exists(cscan_path)
    if not (need_volume or need_cscan):
        return
    scans, lines, samples = group.shape
    factor = max(1, math.ceil(samples / MAX_BINS))
    bins = math.ceil(samples / factor)
    times = line_times(group, samples)
    scale = group.unit_max / group.raw_max * 255.0 / VOLUME_FULL
    volume = None
    if need_volume:
        volume = np.lib.format.open_memmap(data_path + '.tmp.npy', mode='w+', dtype=np.uint8, shape=(lines, scans, bins))
    cscan = {}
    block_scans = max(1, min(64, BLOCK_SAMPLES // (lines * samples)))
    with h5py.File(path, 'r') as h5:
        ds = h5[group.path]
        status = h5[group.status_path] if group.status_path else None
        for first in range(0, scans, block_scans):
            block = np.asarray(ds[first:first + block_scans], dtype=np.int16)
            flags = np.asarray(status[first:first + block_scans]) if status is not None else None
            k = block.shape[0]
            if need_volume:
                padded = block if samples == bins * factor else np.pad(block, ((0, 0), (0, 0), (0, bins * factor - samples)))
                pooled = np.abs(padded).reshape(k, lines, bins, factor).max(axis=3).astype(np.float32) * scale
                volume[:, first:first + k, :] = np.clip(np.round(pooled), 0, 255).astype(np.uint8).transpose(1, 0, 2)
            if need_cscan:
                # All the block's A-scans at once: (k * lines) rows, each with its own beam's times
                results = gates_block(group, block.reshape(k * lines, samples), gates, np.tile(times, (k, 1)), gain)
                has_data = (flags & 1).astype(bool).reshape(k * lines) if flags is not None else np.ones(k * lines, dtype=bool)
                for letter, r in results.items():
                    out = cscan.setdefault(letter, {name: np.full((scans, lines), np.nan, dtype=np.float32)
                                                    for name in ('amplitude', 'peak_time', 'crossing_time')})
                    for name in out:
                        out[name][first:first + k] = np.where(has_data, r[name], np.nan).reshape(k, lines)
            if progress:
                progress(min(1.0, (first + block_scans) / scans))
    if need_volume:
        volume.flush()
        del volume
        os.replace(data_path + '.tmp.npy', data_path)
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({'lines': lines, 'scans': scans, 'bins': bins, 'factor': factor, 'full': VOLUME_FULL}, f)
    if need_cscan:
        arrays = {f'{letter}_{name}': value for letter, out in cscan.items() for name, value in out.items()}
        tmp = cscan_path + '.tmp.npz'
        np.savez(tmp, **arrays)
        os.replace(tmp, cscan_path)
    prune()


def read_volume_line(path, group, line):
    """One line's B-scan from the cached volume: uint8 [scans, bins] (0-255 = 0-VOLUME_FULL %)."""
    info = volume_info(path, group)
    if info is None:
        return None, None
    data_path, _ = _volume_paths(cache_dir(path), group.id)
    volume = np.load(data_path, mmap_mode='r')
    return np.ascontiguousarray(volume[line]), info


def read_cscan(path, group, gates, gain=0.0):
    """{'A_amplitude': [scans, lines], ...} for these gates and gain, or None when not built yet."""
    cscan_path = _cscan_path(cache_dir(path), group.id, gates_key(gates, gain))
    if not os.path.exists(cscan_path):
        return None
    with np.load(cscan_path) as data:
        return {name: data[name] for name in data.files}


# ── background jobs ──────────────────────────────────────────────────────

def job_key(path, group, gates, gain):
    return f'{file_key(path)}|{group.id}|{gates_key(gates, gain)}'


def is_built(path, group, gates, gain=0.0):
    return volume_info(path, group) is not None and read_cscan_exists(path, group, gates, gain)


def read_cscan_exists(path, group, gates, gain=0.0):
    return os.path.exists(_cscan_path(cache_dir(path), group.id, gates_key(gates, gain)))


def ensure(path, group, gates, gain=0.0, background=True):
    """
    Starts building what this group needs (if it isn't built or building) and returns the job's
    {'state': 'done' | 'running' | 'error', 'progress', 'error'}.
    """
    if is_built(path, group, gates, gain):
        return {'state': 'done', 'progress': 1.0, 'error': ''}
    key = job_key(path, group, gates, gain)
    with _lock:
        job = _jobs.get(key)
        if job and job['state'] in ('running', 'done'):
            return dict(job)
        job = _jobs[key] = {'state': 'running', 'progress': 0.0, 'error': '', 'started': time.time()}

    def report(fraction):
        job['progress'] = round(fraction, 3)

    def run():
        try:
            build(path, group, gates, gain, progress=report)
            job['state'], job['progress'] = 'done', 1.0
        except Exception as e:   # shown on the page; the next request may try again
            job['state'], job['error'] = 'error', f'{type(e).__name__}: {e}'

    if background:
        threading.Thread(target=run, daemon=True, name=f'analysis-build-{key}').start()
    else:
        run()
    return dict(job)


def open_group(path, group_id):
    info = open_file(path)
    return info, info.group(group_id)
