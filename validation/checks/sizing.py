"""
L2 - sizing and detection, against indications sized and logged in OmniPC:
    Sizing    exports whose cursors were put on the indication's dB-drop ends (S(r) / S(m) exported,
              role 'sizing'): the page's own sizing (its Size, the same endpoint) at the same peak must
              put the ends where OmniPC's cursors are - within one scan step (OmniPC's cursors sit on
              scan positions) plus OmniPC's displayed digit.
    Detection exports listing every indication a technician logged in the file (role 'detection'):
              Find indications (the page's defaults) must find each one - its scan position within a
              found indication's length (a step either way), its beam / index line within its lines.
              What Find adds besides is listed for review, not counted against it.
"""
import json
import os

from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import resolve, reverse

from analysis.services import detection, nde_data, projections

from . import check, item
from .readings import INCH, MM, _kit_nde

AGAINST = 'OmniPC'


def page_size(factory, path, group, scan, lateral, method):
    """The page's Size at a cell (its sizing endpoint, in-process): {'start', 'end', 'length', ...} in m."""
    url = reverse('analysis-size')
    response = resolve(url).func(factory.get(url, {'path': path, 'group': group, 'scan': scan, 'lateral': lateral, 'method': method}))
    data = json.loads(response.content)
    if response.status_code != 200:
        raise nde_data.NdeDataError(data.get('error') or f'HTTP {response.status_code}')
    return data


def check_sizing(context, entry, spec, nde, factory):
    path = context.kit.full_path(nde)
    info = nde_data.open_file(path)
    group = info.group(spec.get('group', 0))
    projections.ensure(path, group, group.gates, 0.0, background=False)   # the page sizes on its C-scan
    to_unit = INCH if spec.get('units', 'in') == 'in' else MM
    unit = 'in' if to_unit == INCH else 'mm'
    step = abs(group.axes[0].resolution) / to_unit
    method = str(spec.get('sizing') or '6')
    for point in spec['points']:
        cursors = point.get('cursors') or {}
        lateral = point.get('index', point.get('beam'))
        if 'S(r)' not in cursors or 'S(m)' not in cursors or point.get('scan') is None or lateral is None:
            continue
        subject = f"{os.path.basename(nde['path'])} #{point.get('number')}: scan {point['scan']}, line {lateral}"
        try:
            size = page_size(factory, path, group.id, point['scan'], lateral, method)
        except nde_data.NdeDataError as e:
            context.emit(check('Sizing', subject, AGAINST, [item('Sized by the page', 'its ends', str(e), False, 'Sizes')]))
            continue
        theirs = sorted((cursors['S(r)'], cursors['S(m)']))
        ours = sorted((size['start'] / to_unit, size['end'] / to_unit))
        digits = 3 if unit == 'in' else 1
        tol = step + 0.5 * 10 ** -digits
        rule = f'Within a scan step ({step:.{digits + 1}f} {unit}) and the displayed digit'
        context.emit(check('Sizing', subject, AGAINST, [
            item(f'Start (−{method} dB)', f'{theirs[0]:.{digits}f} {unit}', f'{ours[0]:.{digits + 2}f} {unit}', abs(ours[0] - theirs[0]) <= tol, rule),
            item(f'End (−{method} dB)', f'{theirs[1]:.{digits}f} {unit}', f'{ours[1]:.{digits + 2}f} {unit}', abs(ours[1] - theirs[1]) <= tol, rule),
            item('Length', f'{theirs[1] - theirs[0]:.{digits}f} {unit}', f'{ours[1] - ours[0]:.{digits + 2}f} {unit}',
                 abs((ours[1] - ours[0]) - (theirs[1] - theirs[0])) <= 2 * tol, 'Within two scan steps and the displayed digit'),
        ], note=f"OmniPC's reference and measure cursors on the −{method} dB ends; from {spec.get('export') or entry['path']}"))


def check_detection(context, entry, spec, nde):
    path = context.kit.full_path(nde)
    info = nde_data.open_file(path)
    group = info.group(spec.get('group', 0))
    projections.ensure(path, group, group.gates, 0.0, background=False)
    cscan = projections.read_cscan(path, group, group.gates, 0.0)
    found, skipped = detection.detect(path, info, group, group.gates, cscan, 'A')
    step = abs(group.axes[0].resolution)
    to_scan = lambda i: group.axes[0].offset + i * group.axes[0].resolution
    items, matched = [], set()
    for point in spec['points']:
        lateral = point.get('index', point.get('beam'))
        if point.get('scan') is None or lateral is None:
            items.append(item(f"#{point.get('number')}", 'placed in the file', point.get('problem') or 'not placed', False, 'Placed'))
            continue
        where = to_scan(point['scan'])
        hit = next((k for k, f in enumerate(found) if f['scan_start'] - step <= where <= f['scan_end'] + step
                    and f['line_lo'] - 1 <= lateral <= f['line_hi'] + 1), None)
        if hit is not None:
            matched.add(hit)
        items.append(item(f"#{point.get('number')}: scan {point['scan']}, line {lateral}", 'logged in OmniPC',
                          f'found (the app\'s #{hit + 1})' if hit is not None else 'not found', hit is not None,
                          'Inside a found indication (a scan step and a line either way)'))
    extra = len(found) - len(matched)
    logged = len(spec['points'])
    context.emit(check('Detection', f"{os.path.basename(nde['path'])}: {sum(1 for i in items if i['ok'])} of {logged} logged indications found",
                       AGAINST, items,
                       note=f"Find indications (gate A, its defaults) found {len(found)}; {extra} besides the logged ones, for review"
                            + (f"; {len(skipped)} regions couldn't be sized" if skipped else '') + f". From {spec.get('export') or entry['path']}"))


def run(context):
    sizing = [e for e in context.with_role('sizing') if e['path'].lower().endswith('.json')]
    complete = [e for e in context.with_role('detection') if e['path'].lower().endswith('.json')]
    if not sizing and not complete:
        context.message('No sized or fully evaluated OmniPC exports in the kit yet: import one with its options ticked.')
        return
    factory = RequestFactory()
    with override_settings(ANALYSIS_EXTRA_ROOTS=list(getattr(settings, 'ANALYSIS_EXTRA_ROOTS', [])) + [context.kit.root]):
        todo = [(e, 'sizing') for e in sizing] + [(e, 'detection') for e in complete]
        for n, (entry, kind) in enumerate(todo):
            if context.cancelled():
                return
            context.progress(f"{'Sizing' if kind == 'sizing' else 'Finding'}: {entry['path']}", n / len(todo))
            with open(context.kit.full_path(entry), encoding='utf-8') as f:
                spec = json.load(f)
            nde = _kit_nde(context, spec)
            if nde is None:
                context.emit(check(kind.title(), entry['path'], AGAINST, [item('The .nde file is in the kit', spec['file'], 'not in the kit', False, 'Exact')]))
                continue
            if kind == 'sizing':
                check_sizing(context, entry, spec, nde, factory)
            else:
                check_detection(context, entry, spec, nde)
