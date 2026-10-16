"""
L1 - readings: every point OmniPC exported (kit points files, role 'readings') read again by the
Analysis page itself - its readings endpoint, the same JSON the page shows in the readings column - and
compared with OmniPC's value to the digit OmniPC displayed. OmniPC's ^ readings are where each gate's
peak selection puts them (setup.csv's Peak Selection: Highest = the gate's highest sample), its /
readings at the threshold crossing.
"""
import json
import os
import re
from dataclasses import asdict, replace

from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import resolve, reverse

from analysis.services.nde_data import NdeDataError, open_file

from . import check, item

AGAINST = 'OmniPC'
INCH, MM = 0.0254, 0.001
_NUMBERED = re.compile(r'^([A-Z])%\d+$')   # OmniPC's A%1 / B%1: the gate's amplitude


def tolerance(decimals):
    """Half OmniPC's last displayed digit: agreeing to it is the most a displayed value can show."""
    return 0.5 * 10 ** -decimals + 1e-9


def app_name(name):
    """The page's name for an OmniPC reading (A%1 -> A%)."""
    match = _NUMBERED.match(name)
    return f'{match.group(1)}%' if match else name


def _kit_nde(context, spec):
    """The kit entry of the points file's .nde file (by kit path, else by name), or None."""
    wanted = spec['file'].replace('\\', '/')
    entries = [e for e in context.files if e['path'].lower().endswith('.nde')]
    exact = next((e for e in entries if e['path'] == wanted), None)
    return exact or next((e for e in entries if os.path.basename(e['path']).lower() == os.path.basename(wanted).lower()), None)


def page_readings(client, path, group, scan, lateral, gates, gain=0.0):
    """The readings the page shows - its readings endpoint's view, called in-process - SI."""
    url = reverse('analysis-readings')
    response = resolve(url).func(client.get(url, {
        'path': path, 'group': group, 'scan': scan, 'lateral': lateral, 'gain': gain,
        'gates': json.dumps([asdict(g) for g in gates])}))
    data = json.loads(response.content)
    if response.status_code != 200:
        raise NdeDataError(data.get('error') or f'HTTP {response.status_code}')
    return data.get('readings') or {}, data.get('note', '')


def check_points(context, entry, client):
    with open(context.kit.full_path(entry), encoding='utf-8') as f:
        spec = json.load(f)
    nde = _kit_nde(context, spec)
    title = os.path.basename(entry['path'])
    if nde is None:
        context.emit(check('Readings', title, AGAINST, [item('The .nde file is in the kit', spec['file'], 'not in the kit (or failed its fingerprint)', False, 'Exact')]))
        return
    path = context.kit.full_path(nde)
    info = open_file(path)
    group = info.group(spec.get('group', 0))
    to_unit = INCH if spec.get('units', 'in') == 'in' else MM
    unit = 'in' if to_unit == INCH else 'mm'
    detection = spec.get('detection') or {}
    peak_gates = [replace(g, detection=detection.get(_letter(g.name), 'maxpeak')) for g in group.gates]
    edge_gates = [replace(g, detection='edge') for g in group.gates]
    for point in spec['points']:
        lateral = point.get('index', point.get('beam'))
        where = f"#{point.get('number', '?')}: scan {point.get('scan')}" + (
            f", index {point['index']}" if 'index' in point else f", beam {point.get('beam')}" + (f" ({point['angle']:g} deg)" if 'angle' in point else ''))
        subject = f"{os.path.basename(nde['path'])} {where}"
        if point.get('problem') or lateral is None or point.get('scan') is None:
            context.emit(check('Readings', subject, AGAINST, [item('Placed in the file', 'a scan position and beam', point.get('problem') or 'not placed', False, 'Exact')]))
            continue
        items = []
        try:
            by_peak, note = page_readings(client, path, group.id, point['scan'], lateral, peak_gates, point.get('gain', 0.0))
            by_edge, _ = page_readings(client, path, group.id, point['scan'], lateral, edge_gates, point.get('gain', 0.0))
        except NdeDataError as e:
            context.emit(check('Readings', subject, AGAINST, [item('Read by the page', 'readings', str(e), False, 'Exact')]))
            continue
        for name, expected in point['expected'].items():
            decimals = point.get('decimals', {}).get(name, 3)
            values = by_peak if '^' in name else by_edge
            key = app_name(name)
            percent = '%' in name
            shown_unit = '%' if percent else unit
            if key not in values:
                items.append(item(name, f'{expected:.{decimals}f} {shown_unit}', note or 'not given by the page', False,
                                  'The page gives the reading'))
                continue
            measured = values[key] if percent else values[key] / to_unit
            tol = tolerance(decimals)
            items.append(item(name, f'{expected:.{decimals}f} {shown_unit}', f'{measured:.{decimals + 2}f} {shown_unit}',
                              abs(measured - expected) <= tol, f'Same to the displayed digit (within ±{0.5 * 10 ** -decimals:g})'))
        for name, why in (point.get('not_compared') or {}).items():
            items.append(item(name, 'exported', 'not compared', None, why[0].upper() + why[1:]))
        gain = point.get('gain', 0.0)
        context.emit(check('Readings', subject, AGAINST, items,
                           note=f"From {spec.get('export') or spec.get('source') or title}" + (f'; soft gain {gain:+g} dB' if gain else '')))


def _letter(name):
    match = re.search(r'([A-Z])\s*$', name or '')
    return match.group(1) if match else ''


def run(context):
    entries = [e for e in context.with_role('readings') if e['path'].lower().endswith('.json')]
    if not entries:
        context.message('No OmniPC readings in the kit yet: import an OmniPC export.')
        return
    client = RequestFactory()
    # The kit's files are opened through the page's own endpoint, which only opens allowed folders
    with override_settings(ANALYSIS_EXTRA_ROOTS=list(getattr(settings, 'ANALYSIS_EXTRA_ROOTS', [])) + [context.kit.root]):
        for n, entry in enumerate(entries):
            if context.cancelled():
                return
            context.progress(f"Checking {entry['path']}", n / len(entries))
            check_points(context, entry, client)
