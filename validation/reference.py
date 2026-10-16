"""
The independent reference reader: a deliberately small reader of Evident .nde files (HDF5, NDE open
format 4.x - https://ndeformat.com) written straight from the file layout, sharing nothing with the
Analysis page's reader (analysis.services.nde_data). Layer L0 reads every file both ways and compares;
two separate readings that agree bit for bit are the evidence the page shows what the scope recorded.

It reads only what the file states, as stated: the setup JSON, each A-scan dataset in its own sample
type, and the scale from raw values to % of full screen. No layouts are interpreted beyond naming the
dimensions, no defaults are filled in.
"""
import json

import h5py
import numpy as np

SETUP = 'Public/Setup'


def setup(path):
    """The file's setup: the JSON document at /Public/Setup."""
    with h5py.File(path, 'r') as h5:
        raw = h5[SETUP][()]
    return json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)


def groups(path):
    """
    Each group as the file describes it: {id, name, amplitude: {path, dims, value, dtype, shape},
    status: {path, dtype, shape} | None, process: the group's ultrasonic process (dict), kind:
    'ultrasonicPhasedArray' / 'ultrasonicConventional' / None}. A group without an A-scan amplitude
    dataset (TFM) has amplitude None.
    """
    doc = setup(path)
    out = []
    with h5py.File(path, 'r') as h5:
        for g in doc.get('groups') or []:
            datasets = g.get('datasets') or []
            amp = next((d for d in datasets if d.get('dataClass') == 'AScanAmplitude'), None)
            st = next((d for d in datasets if d.get('dataClass') == 'AScanStatus'), None)
            kind, process = None, None
            for p in g.get('processes') or []:
                for k in ('ultrasonicPhasedArray', 'ultrasonicConventional'):
                    if k in p and process is None:
                        kind, process = k, p[k]
            item = {'id': g.get('id'), 'name': g.get('name'), 'amplitude': None, 'status': None,
                    'process': process or {}, 'kind': kind}
            if amp and amp.get('path') in h5:
                ds = h5[amp['path']]
                item['amplitude'] = {'path': amp['path'], 'dims': amp.get('dimensions') or [],
                                     'value': amp.get('dataValue') or {}, 'dtype': str(ds.dtype), 'shape': tuple(ds.shape)}
            if st and st.get('path') in h5:
                ds = h5[st['path']]
                item['status'] = {'path': st['path'], 'dtype': str(ds.dtype), 'shape': tuple(ds.shape)}
            out.append(item)
    return out


def frame(path, group, scan):
    """Everything recorded at one scan position, in the dataset's own sample type: [lateral, samples]
    (a one-line dataset [scan, samples] gives [1, samples])."""
    with h5py.File(path, 'r') as h5:
        data = h5[group['amplitude']['path']][scan]
    return data[None, :] if data.ndim == 1 else data


def status(path, group, scan):
    """The A-scan status bits at one scan position ([lateral]), or None without a status dataset."""
    if not group['status']:
        return None
    with h5py.File(path, 'r') as h5:
        return np.atleast_1d(h5[group['status']['path']][scan])


def percent(raw, group):
    """Raw samples -> the dataset's unit (% of full screen): raw x unitMax / max, in double precision."""
    value = group['amplitude']['value']
    return np.asarray(raw, dtype=np.float64) * (float(value['unitMax']) / float(value['max']))


def dims(group):
    """The amplitude dataset's dimensions: [{axis, quantity, offset, resolution, beams}] as stored."""
    return group['amplitude']['dims'] if group['amplitude'] else []
