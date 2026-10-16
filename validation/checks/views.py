"""
L4 - views: the real Analysis page, served in-process and opened in a headless browser on each kit
file, checked pixel by pixel against the data under each pixel:
    S-scan   at samples picked from the raw frame (independent reader): the sample's position worked out
             here from the file's beam (sound path v t / 2 from its first-sample time, along its refracted
             angle and skew) must be where the page's beam geometry puts it, and the pixel drawn there
             must be the palette's colour for that sample's amplitude
    A-scan   the trace passes through each picked sample's amplitude at its depth
    C-scan   the pixel over a cell is the palette's colour for that cell's value
    Cursor   a click on a sample's pixel moves the cursor to that sample's beam
Points are picked across the amplitude range. The S-scan is zoomed in on each so a sample spans 10
pixels; a pixel touching the point shows it blended with up to a pixel's worth of the neighbouring
samples and lines (worked out from the zoom and the line spacing), so one of the pixels touching it
must have a colour within the palette's colours over the values that blend can give, 2 levels of 255
either way for rounding. An A-scan
without data (or, re-timed to the interface, without its gate I sync) is no data, as in OmniPC.
"""
import json
import math
import os
import random
from urllib.parse import urlencode

import numpy as np

from analysis.services import nde_data
from validation import reference
from validation.browser import Browser, BrowserError
from validation.server import live_server

from . import check, item

AGAINST = 'The data under each pixel'
SLACK = 2            # colour levels either way
SAMPLE_PX = 10       # the S-scan zoomed in on each point: a sample this many pixels long
BINS = [(0, 5), (5, 20), (20, 50), (50, 80), (80, 100), (100, 1e9)]
PER_BIN = 4


def lut_colour(lut, p):
    """The palette's colour at p (0-1) as the shaders sample it: between the 256 entries."""
    x = min(max(p, 0.0), 1.0) * 255
    k = int(math.floor(x))
    k2, f = min(k + 1, 255), x - k
    return [lut[4 * k + c] * (1 - f) + lut[4 * k2 + c] * f for c in range(3)]


def colour_span(lut, p_lo, p_hi):
    """Per channel (min, max) of the palette's colours for p from p_lo to p_hi."""
    lo, hi = min(max(p_lo, 0.0), 1.0), min(max(p_hi, 0.0), 1.0)
    ps = [lo, hi] + [k / 255 for k in range(math.ceil(lo * 255), math.floor(hi * 255) + 1)]
    colours = [lut_colour(lut, p) for p in ps]
    return [(min(c[i] for c in colours), max(c[i] for c in colours)) for i in range(3)]


def within(rgb, span):
    return all(lo - SLACK <= v <= hi + SLACK for v, (lo, hi) in zip(rgb, span))


def pick(values, seed, mask=None):
    """[(line, sample)] spread over the amplitude bands, not at an edge (lines either side have data)."""
    lines, samples = values.shape
    rng = random.Random(seed)
    chosen = []
    for lo, hi in BINS:
        candidates = []
        for b in range(1, lines - 1):
            if mask is not None and not mask[b - 1:b + 2].all():
                continue
            row = values[b, 1:samples - 1]
            candidates += [(b, int(i) + 1) for i in np.nonzero((row >= lo) & (row < hi))[0]]
        rng.shuffle(candidates)
        chosen += candidates[:PER_BIN]
    return chosen


def blend_range(values, line, sample, along, across):
    """(lo, hi) of what a pixel at a sample may show: up to `along` of the way to the samples either side
    and `across` of the way to the lines either side (bilinear blending)."""
    v = values[line, sample]
    ds = [values[line, sample - 1] - v, values[line, sample + 1] - v, 0.0]
    db = [values[line - 1, sample] - v, values[line + 1, sample] - v, 0.0]
    corners = [v + along * a + across * b for a in ds for b in db]
    return min(corners), max(corners)


def beam_geometry(ref, k):
    """(index, depth per metre of sound path, start sound path, sound path per sample) of line k, from the
    file's own description (raster lines: straight down at their index position)."""
    dims = reference.dims(ref)
    us = dims[-1]
    process = ref['process']
    velocity = process.get('velocity', 0.0)
    if len(dims) == 3 and dims[1].get('axis') == 'VCoordinate':
        v = dims[1]
        return {'v0': (v.get('offset') or 0.0) + k * v['resolution'], 'dv': 0.0, 'dz': 1.0,
                'sp0': velocity * (us.get('offset') or 0.0) / 2, 'step': velocity * us['resolution'] / 2}
    beams = dims[1].get('beams') or [{}] if len(dims) == 3 else [{}]
    b = beams[k] if k < len(beams) else {}
    pb = (process.get('beams') or [{}])[min(k, len(process.get('beams') or [{}]) - 1)]
    angle, skew = math.radians(b.get('refractedAngle', pb.get('refractedAngle', 0.0))), math.radians(b.get('skewAngle', pb.get('skewAngle', 90.0)))
    velocity = b.get('velocity', velocity)
    start = b.get('ultrasoundOffset', pb.get('ascanStart', us.get('offset') or 0.0))
    return {'v0': b.get('vCoordinateOffset', 0.0), 'dv': math.sin(angle) * math.sin(skew), 'dz': math.cos(angle),
            'sp0': velocity * start / 2, 'step': velocity * us['resolution'] / 2}


JS_SSCAN = """((points, SAMPLE_PX) => {
    const page = document.getElementById('analysis'), s = page.views.sscan, gl = s.gl;
    const H = s.canvas.height, out = [], px = new Uint8Array(4);
    for (const p of points) {
        const r = s.rays[p.line], sp = r.sp_start + p.sample * r.sp_step;
        // Zoomed in on the point: a sample about 6 pixels long
        const [dx, dy] = s.toDisplayPoint([p.index, p.depth]), across = s.canvas.width * r.sp_step / SAMPLE_PX;
        s.view = [dx, dy, across, across * s.canvas.height / s.canvas.width, 1];
        s.draw();
        const [x, y] = s.toScreen(p.index, p.depth);
        const inside = x >= 1 && y >= 1 && x < s.canvas.width - 1 && y < s.canvas.height - 1;
        const around = [];   // the pixels touching the point
        if (inside) {
            const block = new Uint8Array(2 * 2 * 4), x0 = Math.round(x) - 1, y0 = Math.round(y) - 1;
            gl.readPixels(x0, H - 1 - (y0 + 1), 2, 2, gl.RGBA, gl.UNSIGNED_BYTE, block);
            for (let k = 0; k < 16; k += 4) around.push([block[k], block[k + 1], block[k + 2]]);
        }
        out.push({ index: r.v0 + r.dv * sp, depth: r.dz * sp, x, y, inside, around });
    }
    s.view = null;
    s.draw();
    return out;
})"""

JS_ASCAN = """(points => {
    // The trace is anti-aliased: a pixel it crosses is the trace colour over the background in some
    // proportion (the same in each channel) - its coverage
    const a = document.getElementById('analysis').views.ascan, f = a.frame(), ctx = a.canvas.getContext('2d');
    const trace = [253, 224, 71], ground = [11, 13, 17];
    return points.map(p => {
        const x = f.sx(p.along), y = f.sy(p.value * a.gain);
        const data = ctx.getImageData(Math.round(x) - 2, Math.round(y) - 2, 5, 5).data;
        let coverage = 0;
        for (let i = 0; i < data.length; i += 4) {
            const t = [0, 1, 2].map(c => (data[i + c] - ground[c]) / (trace[c] - ground[c]));
            if (Math.max(...t) - Math.min(...t) < 0.15) coverage = Math.max(coverage, Math.min(...t));
        }
        return { x, y, coverage, along: a.along(p.sample) };
    });
})"""

JS_CSCAN = """(() => {
    const page = document.getElementById('analysis'), v = page.views.cview, st = page.check.state;
    if (!v.hasImage || !st.cscan) return null;
    const { data, scans, lines } = st.cscan, gl = v.gl, H = v.canvas.height, px = new Uint8Array(4);
    const at = (c, r) => data[c * lines + r];
    const [cx, cy, w, h] = v.currentView();
    const perPixelX = Math.max(1, Math.ceil(Math.abs(w / v.axes.dx) / v.canvas.width)), perPixelY = Math.max(1, Math.ceil(Math.abs(h / v.axes.dy) / v.canvas.height));
    const hx = perPixelX + 1, hy = perPixelY + 1;
    const out = [];
    let seed = 7;
    const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    // Across the range: amplitude bands, or tenths of the thickness / depth palette's range
    const bands = v.mode === 'amplitude' ? [[0, 5], [5, 20], [20, 50], [50, 80], [80, 100], [100, 1e9]]
        : Array.from({ length: 10 }, (_, k) => [v.range[0] + k * (v.range[1] - v.range[0]) / 10, v.range[0] + (k + 1) * (v.range[1] - v.range[0]) / 10]);
    const taken = bands.map(() => 0);
    for (let tries = 0; tries < 200000 && out.length < 30; tries++) {
        const c = hx + Math.floor(rand() * (scans - 2 * hx)), r = hy + Math.floor(rand() * Math.max(1, lines - 2 * hy));
        const centre = at(c, r);
        const band = bands.findIndex(([a, b]) => centre >= a && centre < b);
        if (band < 0 || taken[band] >= (v.mode === 'amplitude' ? 5 : 3)) continue;
        let lo = Infinity, hi = -Infinity, bad = false;
        for (let i = c - hx; i <= c + hx && !bad; i++) for (let j = Math.max(0, r - hy); j <= Math.min(lines - 1, r + hy); j++) {
            const value = at(i, j);
            if (!Number.isFinite(value)) { bad = true; break; }
            lo = Math.min(lo, value); hi = Math.max(hi, value);
        }
        if (bad || hi - lo > (v.mode === 'amplitude' ? Math.max(1.0, 0.15 * centre) : (v.range[1] - v.range[0]) * 0.02)) continue;
        taken[band] += 1;
        const [x, y] = v.toScreen(v.axes.x0 + c * v.axes.dx, v.axes.y0 + r * v.axes.dy);
        if (x < 0 || y < 0 || x >= v.canvas.width || y >= v.canvas.height) continue;
        gl.readPixels(Math.floor(x), H - 1 - Math.floor(y), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
        out.push({ scan: c, line: r, value: at(c, r), lo, hi, rgb: [px[0], px[1], px[2]] });
    }
    return { points: out, mode: v.mode, gain: v.gain, range: v.range, palette: v.palettes[v.mode === 'amplitude' ? 'amplitude' : 'range'],
             lut: Array.from(AnalysisPalette.get(v.mode === 'amplitude' ? 'amplitude' : 'range', v.palettes[v.mode === 'amplitude' ? 'amplitude' : 'range'])) };
})()"""


def check_file(context, browser, base, entry):
    path = context.kit.full_path(entry)
    name = os.path.basename(entry['path'])
    info = nde_data.open_file(path)
    group = next((g for g in info.groups if g.layout != nde_data.UNSUPPORTED), None)
    if group is None:
        return
    ref = next(g for g in reference.groups(path) if g['id'] == group.id)
    seed = int(entry['sha256'][:8], 16)
    # The scan position to look at: the strongest of 20 spread along the scan (more of the palette to check)
    count = group.shape[0]
    scan = max(sorted({round(k * (count - 1) / 19) for k in range(20)}), key=lambda s: float(reference.frame(path, ref, s).max()))
    # The page opens a file by the path its own file list gives it (case-folded folders on Windows)
    listed = browser.eval(f"fetch('{base}/analysis/files.json').then(r => r.json()).then(d => [...d.files, ...(d.opened || [])].map(f => f.path))")         if browser.eval('location.href').startswith(base) else None
    if listed is None:
        browser.navigate(f'{base}/analysis/files.json', settle=0.2)
        listed = browser.eval("(() => { const d = JSON.parse(document.body.innerText); return [...d.files, ...(d.opened || [])].map(f => f.path); })()")
    page_path = next((p for p in listed if os.path.normcase(os.path.realpath(p)) == os.path.normcase(os.path.realpath(path))), path)
    browser.navigate(f"{base}/analysis/?{urlencode({'path': page_path, 'group': group.id})}", settle=0.5)
    browser.wait_for("(() => { const c = document.getElementById('analysis').check; return c && c.state.values && c.state.info; })()", timeout=60)
    browser.eval(f"document.getElementById('analysis').check.setScan({scan}).then(() => true)")
    browser.wait_for(f"(() => {{ const s = document.getElementById('analysis').check.state; return s.scan === {scan} && !!s.values; }})()", timeout=30)
    browser.eval('new Promise(r => setTimeout(r, 400))')
    subject = f'{name} · {group.name} · scan line {scan}'

    raw = reference.frame(path, ref, scan)
    values = reference.percent(raw, ref)
    status = reference.status(path, ref, scan)
    mask = None
    if status is not None:
        mask = (status & 1).astype(bool)
        if ref['process'].get('ascanSynchroMode') == 'SynchroGateRelative':
            mask &= ~(status & 4).astype(bool)   # re-timed to the interface: no sync is no data
    gain = browser.eval("document.getElementById('analysis').check.state.gain")
    palette = browser.eval("document.getElementById('amplitude-palette').value")
    lut = browser.eval(f"Array.from(AnalysisPalette.get('amplitude', {json.dumps(palette)}))")

    # ── S-scan: position and colour of picked samples ──
    picks = pick(values, seed, mask)
    points = []
    for line, sample in picks:
        g = beam_geometry(ref, line)
        sp = g['sp0'] + sample * g['step']
        points.append({'line': line, 'sample': sample, 'index': g['v0'] + g['dv'] * sp, 'depth': g['dz'] * sp})
    drawn = browser.eval(f'{JS_SSCAN}({json.dumps(points)}, {SAMPLE_PX})') if points else []
    factor = 10 ** (gain / 20)
    pos_items, colour_items = [], []
    worst = 0.0
    for p, d in zip(points, drawn):
        off = math.hypot(d['index'] - p['index'], d['depth'] - p['depth'])
        worst = max(worst, off)
        # Half a pixel either way at this zoom: along the beam a sample is SAMPLE_PX pixels; across, the
        # lines are as far apart as their positions at this sample's sound path
        g, n = beam_geometry(ref, p['line']), beam_geometry(ref, p['line'] + 1)
        sp = g['sp0'] + p['sample'] * g['step']
        spacing = math.hypot((n['v0'] + n['dv'] * sp) - (g['v0'] + g['dv'] * sp), (n['dz'] - g['dz']) * sp) / g['step'] * SAMPLE_PX
        lo, hi = blend_range(values, p['line'], p['sample'], 1.5 / SAMPLE_PX, min(0.5, 1.5 / max(spacing, 1e-9)))
        span = colour_span(lut, lo * factor / 100, hi * factor / 100)
        value = values[p['line'], p['sample']] * factor
        expected = 'rgb(' + ', '.join(f'{lo:.0f}' if round(lo) == round(hi) else f'{lo:.0f}-{hi:.0f}' for lo, hi in span) + ')'
        if not d['inside']:
            colour_items.append(item(f"Line {p['line']}, sample {p['sample']}: {value:.1f} %", expected, 'outside the view', False, 'Drawn'))
            continue
        best = min(d['around'], key=lambda rgb: sum(max(lo - v, 0, v - hi) for v, (lo, hi) in zip(rgb, span)))
        colour_items.append(item(f"Line {p['line']}, sample {p['sample']}: {value:.1f} %", expected, 'rgb({}, {}, {})'.format(*best),
                                 within(best, span), f'The palette ({palette}) colour, ±{SLACK} levels'))
    pos_items.append(item(f'Positions of {len(points)} samples (index, depth)', 'v t / 2 along the beam from the file',
                          f'largest difference {worst * 1e6:.3f} µm', worst <= 1e-6, 'Within 1 µm'))
    context.emit(check('S-scan', subject, AGAINST, pos_items + colour_items,
                       note=f'Colours read from the S-scan as drawn, zoomed in on each point (a sample {SAMPLE_PX} pixels long); the expected colours span what half a pixel of blending with the neighbouring samples and lines can give.'))

    # ── A-scan: the trace through flat samples of a line with data (the cursor moved there) ──
    usable_lines = values.max(axis=1) if mask is None else np.where(mask, values.max(axis=1), -1)
    line = int(np.argmax(usable_lines))   # the line with the strongest signal
    browser.eval(f"document.getElementById('analysis').check.setLateral({line}, true) || true")
    browser.eval('new Promise(r => setTimeout(r, 300))')
    gate_levels = [g.threshold for g in group.gates]
    rng = random.Random(seed)
    a_points = []
    n = values.shape[1]
    for lo, hi in BINS[:-1]:   # the trace is drawn up to 100 %
        usable = [s for s in range(n // 20, n - n // 50) if lo <= values[line, s] * factor < hi and values[line, s] * factor >= 3
                  and all(abs(values[line, s] * factor - t) > 2.5 for t in gate_levels)]
        rng.shuffle(usable)
        a_points += usable[:5]
    a_points = sorted(a_points)
    a_items = []
    if a_points:
        geometry = beam_geometry(ref, line)
        along = [(geometry['sp0'] + s * geometry['step']) * (geometry['dz'] if browser.eval("document.getElementById('analysis').views.ascan.axis") == 'depth' else 1.0)
                 for s in a_points]
        traced = browser.eval(f"{JS_ASCAN}({json.dumps([{'sample': s, 'along': a, 'value': float(values[line, s])} for s, a in zip(a_points, along)])})")
        for s, a, t in zip(a_points, along, traced):
            a_items.append(item(f'Sample {s}: {values[line, s] * factor:.1f} % at {a * 1000:.3f} mm', 'the trace through it (within 2 pixels)',
                                f"{'on the trace' if t['coverage'] >= 0.35 else 'no trace'} at ({t['x']:.0f}, {t['y']:.0f}) px (axis position {t['along'] * 1000:.3f} mm)",
                                t['coverage'] >= 0.35 and abs(t['along'] - a) <= 1e-9, 'Drawn at its amplitude and depth'))
    context.emit(check('A-scan', f'{subject} · line {line}', AGAINST, a_items or [item('Flat samples to check', 'some', 'none', None, 'Shown')]))

    # ── Cursor: a click on a picked sample's pixel moves the cursor to its line ──
    # A point whose pixel doesn't grab a gate's edge or a cursor line (a click there would move that instead)
    target, at = None, None
    for p in points:
        if p['line'] == line:
            continue
        spot = browser.eval(f"(() => {{ const s = document.getElementById('analysis').views.sscan, b = s.overlay.getBoundingClientRect(); "
                            f"const [x, y] = s.toScreen({p['index']}, {p['depth']}); const e = {{ clientX: b.left + x / devicePixelRatio, clientY: b.top + y / devicePixelRatio }}; "
                            f"return s.grabLine(e) || s.grabGate(e) ? null : [e.clientX, e.clientY]; }})()")
        if spot:
            target, at = p, spot
            break
    if target:
        browser.click(*at)
        browser.eval('new Promise(r => setTimeout(r, 400))')
        now = browser.eval("document.getElementById('analysis').check.state.lateral")
        context.emit(check('Cursor', f"{subject} · click on line {target['line']}", AGAINST, [
            item('The cursor goes to the line clicked', str(target['line']), str(now), now == target['line'], 'Exact')]))

    # ── C-scan: the colour over picked cells ──
    try:
        browser.wait_for("(() => { const v = document.getElementById('analysis').views.cview; return v.hasImage; })()", timeout=120)
    except BrowserError:
        context.emit(check('C-scan', f'{name} · {group.name}', AGAINST, [item('Drawn', 'yes', 'not drawn in 2 minutes', None, 'Drawn')], kind='info'))
        return
    browser.eval('new Promise(r => setTimeout(r, 400))')
    c = browser.eval(JS_CSCAN)
    c_items = []
    for p in (c or {}).get('points', []):
        if c['mode'] == 'amplitude':
            to_p = lambda v: v * c['gain'] / 100
            label = f"{p['value']:.1f} %"
        else:
            r0, r1 = c['range']
            to_p = lambda v, r0=r0, r1=r1: (v - r0) / max(r1 - r0, 1e-12)
            label = f"{p['value'] * 1000:.3f} mm"
        span = colour_span(c['lut'], to_p(p['lo']), to_p(p['hi']))
        expected = 'rgb(' + ', '.join(f'{lo:.0f}' if round(lo) == round(hi) else f'{lo:.0f}-{hi:.0f}' for lo, hi in span) + ')'
        c_items.append(item(f"Scan {p['scan']}, line {p['line']}: {label}", expected, 'rgb({}, {}, {})'.format(*p['rgb']),
                            within(p['rgb'], span), f"The palette ({c['palette']}) colour, ±{SLACK} levels"))
    kind = browser.eval("document.getElementById('cscan-kind').selectedOptions[0]?.text || ''")
    context.emit(check('C-scan', f'{name} · {group.name} · {kind}', AGAINST,
                       c_items or [item('Flat cells to check', 'some', 'none', None, 'Shown')],
                       note="Cell values are the app's C-scan data (its numbers are checked by L1 and L6); this checks they're drawn where and as they should be."))


def run(context):
    entries = [e for e in context.files if e['path'].lower().endswith('.nde')]
    chosen = [e for e in entries if 'views' in (e.get('roles') or [])] or entries
    if not chosen:
        context.message('No .nde files in the kit.')
        return
    context.progress('Starting the app and a browser', 0.02)
    try:
        with live_server(context.kit.root) as base, Browser(1600, 1000, timeout=120) as browser:
            for n, entry in enumerate(chosen):
                if context.cancelled():
                    return
                context.progress(f"Opening {entry['path']} in the page", (n + 0.1) / len(chosen))
                check_file(context, browser, base, entry)
            if browser.errors:
                context.emit(check('Page', 'Script errors', AGAINST, [item('Errors in the page', 'none', '; '.join(map(str, browser.errors[:3])), False, 'None')]))
    except BrowserError as e:
        context.emit(check('Views', 'The page in a browser', AGAINST, [item('Run in a browser', 'Edge or Chrome', str(e), False, 'Runs')]))
