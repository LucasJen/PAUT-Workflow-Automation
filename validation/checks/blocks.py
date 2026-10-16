"""
L3 - physical accuracy: calibration blocks with known reflectors. A block definition (kit blocks/*.json,
role 'block') names an imported OmniPC export of the block's scan (its points file) and, for each
reflector, the indication number it was logged as and where the reflector really is (from the block's
drawing or certificate) with the tolerance allowed:
    {"block": "ASME basic block 1.0 in, S/N 1234", "drawing": "pictures/block 1234.pdf", "units": "in",
     "points": "points/block scan G0.json",
     "reflectors": [{"indication": 1, "name": "SDH at 1/4 T", "depth": 0.250, "index": 1.500,
                     "tolerance": {"depth": 0.020, "index": 0.040}}]}
At each reflector the page's readings (DA^ for depth, PA^ for its distance from the probe's index
position) are compared with the true position, and OmniPC's (from the export) are shown beside them:
the app must be within the tolerance and as close as OmniPC (to its displayed digit).
"""
import json
import os
from dataclasses import replace

from django.conf import settings
from django.test import RequestFactory, override_settings

from analysis.services import nde_data

from . import check, item
from .readings import INCH, MM, _kit_nde, _letter, page_readings

AGAINST = 'The block as drawn'
READING = {'depth': 'DA^', 'index': 'PA^'}


def check_block(context, entry, factory):
    with open(context.kit.full_path(entry), encoding='utf-8') as f:
        block = json.load(f)
    points_entry = next((e for e in context.files if e['path'] == block.get('points')), None)
    title = block.get('block') or os.path.basename(entry['path'])
    if points_entry is None:
        context.emit(check('Block', title, AGAINST, [item('Its scan, exported from OmniPC', block.get('points'), 'not in the kit', False, 'In the kit')]))
        return
    with open(context.kit.full_path(points_entry), encoding='utf-8') as f:
        spec = json.load(f)
    nde = _kit_nde(context, spec)
    if nde is None:
        context.emit(check('Block', title, AGAINST, [item('The block scan (.nde) is in the kit', spec['file'], 'not in the kit', False, 'In the kit')]))
        return
    path = context.kit.full_path(nde)
    info = nde_data.open_file(path)
    group = info.group(spec.get('group', 0))
    to_unit = INCH if block.get('units', spec.get('units', 'in')) == 'in' else MM
    unit = 'in' if to_unit == INCH else 'mm'
    digit = 0.0005 if unit == 'in' else 0.005
    gates = [replace(g, detection=(spec.get('detection') or {}).get(_letter(g.name), 'maxpeak')) for g in group.gates]
    for reflector in block.get('reflectors') or []:
        point = next((p for p in spec['points'] if p.get('number') == reflector.get('indication')), None)
        subject = f"{title}: {reflector.get('name', '#' + str(reflector.get('indication')))}"
        if point is None or point.get('scan') is None:
            context.emit(check('Reflector', subject, AGAINST, [item('Logged in the export', f"indication {reflector.get('indication')}", 'not found', False, 'Logged')]))
            continue
        lateral = point.get('index', point.get('beam'))
        values, _ = page_readings(factory, path, group.id, point['scan'], lateral, gates, point.get('gain', 0.0))
        items = []
        for axis, reading in READING.items():
            if reflector.get(axis) is None:
                continue
            truth = float(reflector[axis])
            tol = float((reflector.get('tolerance') or {}).get(axis, 0.02 if unit == 'in' else 0.5))
            ours = values.get(reading)
            theirs = (point.get('expected') or {}).get(reading)
            if ours is None:
                items.append(item(f'{axis.title()} ({reading}): the app', f'{truth:.3f} {unit}', 'no reading', False, f'Within ±{tol:g} {unit}'))
                continue
            ours /= to_unit
            items.append(item(f'{axis.title()} ({reading}): the app', f'{truth:.3f} {unit} (±{tol:g})', f'{ours:.4f} {unit} (error {ours - truth:+.4f})',
                              abs(ours - truth) <= tol, f'Within ±{tol:g} {unit} of the block'))
            if theirs is not None:
                items.append(item(f'{axis.title()} ({reading}): OmniPC', f'{truth:.3f} {unit}', f'{theirs:.3f} {unit} (error {theirs - truth:+.4f})', None,
                                  'For comparison'))
                items.append(item(f'{axis.title()}: the app as close as OmniPC', f'|error| ≤ {abs(theirs - truth):.4f} {unit}',
                                  f'{abs(ours - truth):.4f} {unit}', abs(ours - truth) <= abs(theirs - truth) + digit, "Within OmniPC's displayed digit"))
        context.emit(check('Reflector', subject, AGAINST, items,
                           note=f"{os.path.basename(nde['path'])}, indication {reflector.get('indication')} (scan {point['scan']}, line {lateral})"
                                + (f"; drawing {block['drawing']}" if block.get('drawing') else '')))


def run(context):
    blocks = [e for e in context.with_role('block') if e['path'].lower().endswith('.json')]
    if not blocks:
        context.message('No calibration blocks in the kit yet: scan one, import its OmniPC export, and add its definition (validation/data/block_example.json).')
        return
    factory = RequestFactory()
    with override_settings(ANALYSIS_EXTRA_ROOTS=list(getattr(settings, 'ANALYSIS_EXTRA_ROOTS', [])) + [context.kit.root]):
        for n, entry in enumerate(blocks):
            context.progress(f"Block {entry['path']}", n / len(blocks))
            check_block(context, entry, factory)
