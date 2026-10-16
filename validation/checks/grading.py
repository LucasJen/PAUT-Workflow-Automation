"""
L5 - grading: the page's own grading code (analysis/static/analysis/js/criteria.js, the file the
Indications panel runs) run in a headless browser over the case table written from 100-UT-020's §8
(B31.1) and §9 (B31.3) - every boundary: T at 0.75 / 2.25 in, lengths at and just over the allowed,
amplitudes at and just over the reference level and 20 % of it. Also the amplitude at the reference
gain each grade starts from, worked out here independently.
"""
import json
import math
import os

from django.contrib.staticfiles import finders

from validation.browser import Browser, BrowserError

from . import check, item

IN = 0.0254
CASES = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'criteria_100-UT-020.json')
AGAINST = '100-UT-020 (Rev 9)'
NAMES = {'b31.1': 'B31.1 (§8)', 'b31.3': 'B31.3 (§9)'}


def at_reference(case):
    """The amplitude at the reference gain, worked out from the case (not with the page's code)."""
    sizing, readings = case.get('sizing') or {}, case.get('readings') or {}
    if sizing.get('saturated'):
        return math.inf
    if 'peak_amplitude' in sizing:
        recorded = sizing['peak_amplitude'] * 10 ** (-sizing.get('base_gain', case.get('gain', 0)) / 20)
    else:
        recorded = readings['A%'] * 10 ** (-case.get('gain', 0) / 20)
    ref, scanned = case.get('reference_gain'), case.get('instrument_gain')
    return recorded * 10 ** ((ref - scanned) / 20) if ref and scanned is not None else recorded


def _amp(value):
    return 'saturated' if value in ('saturated', math.inf) else ('none' if value is None else f'{value:g} %')


def run(context):
    with open(CASES, encoding='utf-8') as f:
        table = json.load(f)
    source = finders.find('analysis/js/criteria.js')
    if not source:
        raise FileNotFoundError('analysis/js/criteria.js')
    with open(source, encoding='utf-8') as f:
        code = f.read()
    context.progress('Starting the browser', 0.05)
    try:
        browser = Browser().__enter__()
    except BrowserError as e:
        context.emit(check('Grading', 'The page\'s grading code', AGAINST, [item('Run in a browser', 'Edge or Chrome', str(e), False, 'Runs')]))
        return
    try:
        browser.eval(code + '\n;true')
        cases = table['cases']
        inputs = [{'criteria': c['criteria'], 'amplitude': 'Infinity' if c['amplitude'] == 'saturated' else c['amplitude'],
                   'reference': 80, 'length': None if c['length'] is None else c['length'] * IN,
                   'thickness': None if c['T'] is None else c['T'] * IN} for c in cases]
        results = browser.eval(f"""(() => {{
            const cases = {json.dumps(inputs)};
            return cases.map(c => AnalysisCriteria.grade(c.criteria, {{ ...c, amplitude: c.amplitude === 'Infinity' ? Infinity : c.amplitude }}));
        }})()""")
        for case, result in zip(cases, results):
            subject = (f"{NAMES[case['criteria']]} · T {'none' if case['T'] is None else format(case['T'], '.3f') + ' in'} · "
                       f"{_amp(case['amplitude'])} of 80 % · length {'none' if case['length'] is None else format(case['length'], '.3f') + ' in'}")
            got = result['grade'] if result else 'none'
            context.emit(check('Grading', subject, AGAINST, [
                item('Grade', table['grades'][case['expect']], table['grades'].get(got, got), got == case['expect'], f"§{case['clause']}: {case['why']}"),
            ], note=f"The page's reason: {result['reason']}" if result else ''))
        context.progress('Amplitude at the reference gain', 0.8)
        ref_cases = table['reference_gain_cases']
        got = browser.eval(f"""(() => {{
            const cases = {json.dumps(ref_cases)};
            return cases.map(c => {{ const v = AnalysisCriteria.atReference({{ readings: c.readings, sizing: c.sizing, gain: c.gain }},
                {{ reference_gain: c.reference_gain, instrument_gain: c.instrument_gain }}); return v === Infinity ? 'Infinity' : v; }});
        }})()""")
        for case, value in zip(ref_cases, got):
            want = at_reference(case)
            measured = math.inf if value == 'Infinity' else value
            ok = (want == measured) if math.isinf(want) else (measured is not None and abs(measured - want) <= 1e-9 * max(1, abs(want)))
            context.emit(check('Amplitude at the reference gain', case['why'], 'Worked out independently', [
                item('% at the reference gain', 'saturated' if math.isinf(want) else f'{want:.6f} %',
                     'saturated' if measured == math.inf else (f'{measured:.6f} %' if measured is not None else 'none'), ok,
                     'Equal (to 1 part in a billion): recorded % x 10^(-soft gain / 20) x 10^((reference gain - recorded gain) / 20)')]))
        if browser.errors:
            context.emit(check('Grading', 'Script errors', AGAINST, [item('Errors in the page', 'none', '; '.join(browser.errors[:3]), False, 'None')]))
    finally:
        browser.__exit__(None, None, None)
    context.progress('Sending indications to each report type', 0.9)
    from . import export
    export.run(context)
    context.message(f"{len(table['cases'])} cases from {table['procedure']} - {table['status']}")
