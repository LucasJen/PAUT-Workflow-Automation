"""
L1 (setups) - the file's setup as OmniPC reads it (setup.csv in an OmniPC export: role 'setup') against
what the app reads from the same file: part thickness, gain, wave type, velocity, digitizing frequency,
points per A-scan, the sectorial angles, and each gate's start, width (sound path), threshold and
synchronisation. Each value must equal OmniPC's to the digit it displays.
"""
import json
import os
import re

from analysis.services import nde_data

from . import check, item
from .readings import _kit_nde

AGAINST = "OmniPC's setup.csv"
UNITS = {'in': 0.0254, 'in.': 0.0254, 'mm': 0.001}
WAVES = {'Shear': 'TransversalVertical', 'Longitudinal': 'Longitudinal'}


def _number(text):
    """(value, decimals, unit) of a setup.csv cell like '0.1276 in./µs' or '43.0 °', or None."""
    match = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*(.*?)\s*$', text or '')
    if not match:
        return None
    number = match.group(1)
    return float(number), len(number.split('.')[1]) if '.' in number else 0, match.group(2)


def _same(app, shown):
    """The app's value against OmniPC's displayed one: equal to half its last digit."""
    value, decimals, _ = shown
    return abs(app - value) <= 0.5 * 10 ** -decimals + 1e-9


def check_setup(context, entry):
    with open(context.kit.full_path(entry), encoding='utf-8') as f:
        spec = json.load(f)
    nde = _kit_nde(context, spec)
    subject = os.path.basename(spec['file'])
    if nde is None:
        context.emit(check('Setup', subject, AGAINST, [item('The .nde file is in the kit', spec['file'], 'not in the kit', False, 'In the kit')]))
        return
    info = nde_data.open_file(context.kit.full_path(nde))
    group = next((g for g in info.groups if g.layout != nde_data.UNSUPPORTED), None)
    values, gates = spec['setup']['values'], spec['setup']['gates']
    items = []
    rule = "Equal to OmniPC's displayed digit"

    def compare(name, app, convert=lambda v, unit: v, label=None):
        shown = _number(values.get(name, ''))
        if shown is None or app is None:
            return
        got = convert(app, shown[2])
        if got is None:
            return
        items.append(item(label or name, values[name], f'{got:.{shown[1] + 2}f} {shown[2]}'.strip(), _same(got, shown), rule))

    length = lambda metres, unit: metres / UNITS[unit.split('/')[0]] if unit.split('/')[0] in UNITS else None
    compare('Thickness', info.specimen.get('thickness'), length)
    compare('Gain', group.instrument_gain)
    compare('Points Quantity', group.ultrasound_axis.quantity)
    compare('Velocity', group.velocity, lambda v, unit: v / UNITS[unit.split('/')[0]] / 1e6 if unit.split('/')[0] in UNITS else None)
    compare('Net Digit. Frequency', 1.0 / group.ultrasound_axis.resolution / 1e6 if group.ultrasound_axis.resolution else None)
    if group.layout == nde_data.BEAMS and len(group.beams) > 1 and group.formation == 'sectorial':
        angles = [b.refracted_angle for b in group.beams]
        compare('Start Angle', min(angles))
        compare('Stop Angle', max(angles))
        compare('Angle Resolution', (max(angles) - min(angles)) / (len(angles) - 1))
    wave = values.get('Wave Type', '').strip()
    if wave in WAVES:
        items.append(item('Wave Type', wave, group.wave_mode, group.wave_mode == WAVES[wave], 'The same'))
    by_letter = {g.name.strip().split()[-1].upper(): g for g in group.gates}
    for row in gates:
        gate = by_letter.get(row['name'].upper())
        if gate is None:
            items.append(item(f"Gate {row['name']}", 'in the setup', 'not in the app', False, 'The same gates'))
            continue
        velocity = group.velocity or (group.beams[0].velocity if group.beams else 0.0)
        # A true-depth gate is listed in true depth (the same depths on every beam); the others in sound path
        if gate.geometry == 'TrueDepth' and gate.depth_start is not None:
            extent, kind = (('start', gate.depth_start), ('width', gate.depth_end - gate.depth_start)), 'true depth'
        else:
            extent, kind = (('start', velocity * gate.start / 2), ('width', velocity * gate.length / 2)), 'sound path'
        for field, metres in extent:
            shown = _number(row.get(field, ''))
            if shown is None or shown[2].split('/')[0] not in UNITS:
                continue
            value = metres / UNITS[shown[2].split('/')[0]]
            items.append(item(f"Gate {row['name']} {field} ({kind})", row[field], f'{value:.{shown[1] + 2}f} {shown[2]}', _same(value, shown), rule))
        shown = _number(row.get('threshold', ''))
        if shown:
            items.append(item(f"Gate {row['name']} threshold", row['threshold'], f'{gate.threshold:g} %', _same(gate.threshold, shown), rule))
        synchro = row.get('synchro', '').strip()
        if synchro:
            app_sync = 'Pulse' if gate.sync_mode == 'Pulse' else f"{next((g.name.split()[-1] for g in group.gates if g.id == gate.sync_gate), '?')}"
            items.append(item(f"Gate {row['name']} synchro", synchro, app_sync,
                              (synchro == 'Pulse') == (gate.sync_mode == 'Pulse') and (synchro == 'Pulse' or synchro.startswith(app_sync)),
                              'The same'))
    context.emit(check('Setup', f"{subject} · {group.name}", AGAINST, items, note=f"From {spec.get('export')}"))


def run(context):
    entries = [e for e in context.with_role('setup') if e['path'].lower().endswith('.json')]
    for n, entry in enumerate(entries):
        if context.cancelled():
            return
        context.progress(f"Setup {entry['path']}", n / max(1, len(entries)))
        check_setup(context, entry)
