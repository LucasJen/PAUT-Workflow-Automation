"""
The setup sheet: one picture per setup with everything the instrument's setup report shows
(instrument and probe, UT settings, gates, TCG, focal laws) and a drawing of the probe, wedge and
beams in the part, made from the setup's .nde (Setup.nde_sheet, written by nde_parser's sheet()).
It replaces the calibration screenshots under a setup's calibration data: the long form puts it
under the Equipment Details table, the corrosion form in its Setup Information picture box.

sheet_png(setup, width_in, height_in) lays the tables out at that size, gives the drawing the
height left over and returns PNG bytes (None when the setup has no .nde data).
"""
import io
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

from .scan_plan.render import render_scene
from .scan_plan.scene import Scene

DPI = 300
M_TO_IN = 39.37007874
MIN_DRAWING_IN = 1.6          # the drawing never gets less than this; the sheet grows instead (and is scaled to fit)

INK = (35, 35, 35)
LABEL = (95, 95, 95)
RULE = (150, 150, 150)
HEAD_FILL = (232, 232, 232)
TABLE_LINE = (120, 140, 190)


def load(setup):
    """The setup's sheet data, or None."""
    try:
        data = json.loads(setup.nde_sheet or '')
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and data else None


# ── Formatting (the file is SI; the sheet is in the setup's units) ───────────────────────────

class Units:
    def __init__(self, system):
        self.metric = system == 'metric'

    def length(self, metres, signed=False):
        if metres is None:
            return ''
        text = f'{metres * 1000:.2f} mm' if self.metric else f'{metres * M_TO_IN:.3f} in'
        return text

    def velocity(self, m_per_s):
        if m_per_s is None:
            return ''
        return f'{m_per_s:.0f} m/s' if self.metric else f'{m_per_s / 25400:.4f} in/µs'

    def path(self, seconds, velocity, angle=0.0):
        """A round-trip time as half-path distance (true depth with `angle`) at the part velocity."""
        if seconds is None or not velocity:
            return ''
        return self.length(seconds * velocity / 2 * math.cos(math.radians(angle or 0)))


def _num(value, decimals=2, unit=''):
    if value is None or value == '':
        return ''
    try:
        text = f'{float(value):.{decimals}f}'
    except (TypeError, ValueError):
        return str(value)
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    text = '0' if text in ('-0', '') else text
    return f'{text}{unit}'


def _first_angle(data):
    beams = data.get('beams') or []
    return beams[0][1] if beams else 0.0


def sections(data, system):
    """[(title, kind, content)]: 'pairs' [(label, value)], 'table' (headers, rows)."""
    u = Units(system)
    inst, probe, wedge, ut, law = (data.get(k, {}) for k in ('instrument', 'probe', 'wedge', 'ut', 'law'))
    velocity = ut.get('velocity')
    angle = _first_angle(data)
    axes = data.get('axes', {})

    instrument = [
        ('Instrument', inst.get('platform', '')), ('Model', inst.get('model', '')),
        ('Instrument serial', inst.get('serial', '')), ('Software', inst.get('software', '')),
        ('Probe model', probe.get('model', '')), ('Probe serial', probe.get('serial', '')),
        ('Frequency', _num((probe.get('frequency') or 0) / 1e6 or None, 2, ' MHz')),
        ('Probe aperture', _num(probe.get('elements'), 0)),
        ('Pitch', u.length(probe.get('pitch'))),
        ('Wedge model', wedge.get('model', '')), ('Wedge angle', _num(wedge.get('angle'), 2, '°')),
        ('Wedge velocity', u.velocity(wedge.get('velocity'))),
        ('First element height', u.length(wedge.get('first_element_height'))),
        ('Scan offset', u.length(probe.get('scan_offset'))),
        ('Index offset', u.length(probe.get('index_offset'))),
        ('Probe skew', _num(probe.get('skew'), 1, '°')),
    ]
    setup = [
        ('Law config.', law.get('formation', '')), ('Mode', ut.get('mode', '')),
        ('Wave type', ut.get('wave_mode', '')),
        ('Gain', _num(ut.get('gain'), 1, ' dB')), ('Reference gain', _num(ut.get('reference_gain'), 1, ' dB')),
        ('Beam delay', _num((ut.get('beam_delay') or 0) * 1e6 if 'beam_delay' in ut else None, 2, ' µs')),
        ('Start (true depth)', u.path(ut.get('ascan_start'), velocity, angle)),
        ('Range (true depth)', u.path(ut.get('ascan_length'), velocity, angle)),
        ('Start (sound path)', u.path(ut.get('ascan_start'), velocity)),
        ('Range (sound path)', u.path(ut.get('ascan_length'), velocity)),
        ('Velocity', u.velocity(velocity)),
        ('Digitizing freq.', _num((ut.get('digitizing') or 0) / 1e6 or None, 0, ' MHz')),
        ('Net digitizing freq.', _num((ut.get('net_digitizing') or 0) / 1e6 or None, 1, ' MHz')),
        ('Compression', _num(ut.get('compression'), 0)), ('Points quantity', _num(ut.get('points'), 0)),
        ('Averaging factor', _num(ut.get('averaging'), 0)), ('Rectification', ut.get('rectification', '')),
        ('Band-pass filter', _filter_text(ut.get('filter'))), ('Video filter', ut.get('smoothing', '')),
        ('Pulse width', _num((ut.get('pulse_width') or 0) * 1e9 or None, 1, ' ns')),
        ('Voltage', _num(ut.get('voltage'), 0, ' V')),
        ('Acq. rate', _num(inst.get('acquisition_rate'), 1, ' Hz')),
        (f"{axes.get('scan', {}).get('name', 'Scan')} resolution", u.length(axes.get('scan', {}).get('resolution'))),
        (f"{axes.get('index', {}).get('name', 'Index')} resolution", u.length(axes.get('index', {}).get('resolution'))),
    ]
    calculator = [
        ('Law configuration', ' '.join(v for v in (law.get('formation'), law.get('angles')) if v)),
        ('Element qty used', _num(law.get('aperture'), 0)),
        ('First element', _num(law.get('first_element'), 0)), ('Last element', _num(law.get('last_element'), 0)),
        ('Element step', _num(law.get('element_step'), 2)),
        ('Angle resolution', law.get('angle_step', '') or '-'),
        ('Focus', ' '.join(v for v in (law.get('focus_mode', ''), u.length(law.get('focus_distance'))) if v)),
    ]

    gates = [(g.get('name', ''), u.path(g.get('start'), velocity), u.path(g.get('length'), velocity),
              _num(g.get('threshold'), 0, ' %'), g.get('synchro', '')) for g in data.get('gates') or []]
    tcg = [(str(i), u.path(t, velocity, angle), _num(gain, 1, ' dB'))
           for i, (t, gain) in enumerate(data.get('tcg') or [], start=1)]

    out = [('Instrument & Probe Characteristics', 'pairs', [p for p in instrument if p[1]]),
           ('Setup', 'pairs', [p for p in setup if p[1]])]
    if gates:
        out.append(('Gates', 'table', (('Gate', 'Start', 'Width', 'Threshold', 'Synchro'), gates)))
    if tcg:
        out.append(('TCG', 'tcg', tcg))
    out.append(('Calculator', 'pairs', [p for p in calculator if p[1]]))
    return out


def _filter_text(text):
    if not text:
        return ''
    return text if any(c.isalpha() for c in text) else f'{text} MHz'


# ── Drawing: the probe, wedge and beams in the part (a scan plan scene) ──────────────────────

def _inch(metres, default=None):
    return metres * M_TO_IN if metres is not None else default


def drawing_scene(data, setup, aspect, units, width_px=2000):
    """
    The probe on its wedge and the beams through the part, in the plane of the probe's elements,
    as a scan plan Scene (inches; depth down) with bounds padded to `aspect` (height / width), with
    room for its labels when drawn `width_px` wide.
    """
    u = Units(units)
    probe, wedge, ut, part = (data.get(k, {}) for k in ('probe', 'wedge', 'ut', 'part'))
    t = _inch(part.get('thickness')) or _setup_thickness(setup)
    assumed = t is None
    t = t or 1.0
    elements = int(probe.get('elements') or 1)
    pitch = _inch(probe.get('pitch'), 0.6 / 25.4 if elements > 1 else 0.0)
    a = math.radians(wedge.get('angle') or 0.0)
    cos_a, sin_a = math.cos(a), math.sin(a)
    has_wedge = bool(wedge.get('model') or wedge.get('first_element_height'))
    h1 = _inch(wedge.get('first_element_height'), 0.0) if has_wedge else 0.0
    v_part = ut.get('velocity') or 5900.0
    v_wedge = wedge.get('velocity') or 2330.0
    water = has_wedge and v_wedge < 1700        # HydroFORM / water column
    array = (elements - 1) * pitch

    # First element at x = 0; the wedge front is the primary offset ahead of it
    offset = _inch(wedge.get('primary_offset'))
    front = -offset if offset is not None else array * cos_a + 0.15
    length = _inch(wedge.get('length'), front + 0.3)
    back = front - length
    height = _inch(wedge.get('height'), h1 + array * sin_a + 0.25)

    def face(s):
        return (s * cos_a, -(h1 + s * sin_a))

    scene = Scene(0, 1, 0, 1, False)

    # Beams: a few of the focal laws (all of them when there are only a few), and the zone they cover
    beams = data.get('beams') or []
    shown = beams if len(beams) <= 9 else [beams[round(i * (len(beams) - 1) / 8)] for i in range(9)]
    start, length = ut.get('ascan_start'), ut.get('ascan_length')
    reach = _inch((start + length) * v_part / 2) if start is not None and length and ut.get('velocity') else None
    paths = []
    for centre, angle in beams:
        sin_r = math.sin(math.radians(angle))
        sin_i = sin_r * v_wedge / v_part if has_wedge else sin_r
        if abs(sin_i) >= 1:
            continue
        ex, ey = face(centre * pitch)
        exit_x = ex + (-ey) * math.tan(math.asin(sin_i))
        end = (exit_x + t * math.tan(math.radians(angle)), t)
        # Angle beams: the second leg too, back up to the scanning surface, as the weld scan plans draw
        skip = (end[0] + t * math.tan(math.radians(angle)), 0.0) if abs(angle) >= 5 else None
        # ...but no further than the A-scan's range (a steep beam would otherwise run off far past it)
        if reach:
            end, skip = _clip((exit_x, 0.0), end, skip, reach)
        paths.append(((ex, ey), (exit_x, 0.0), end, angle, (centre, angle) in map(tuple, shown), skip))

    xs = [front, back] + [p[1][0] for p in paths] + [(p[5] or p[2])[0] for p in paths]
    x_lo, x_hi = min(xs) - 0.25, max(xs) + 0.25
    top = max(height, h1 + array * sin_a) + 0.2

    # Part
    scene.add('polygon', points=[(x_lo, 0), (x_hi, 0), (x_hi, t), (x_lo, t)], fill='plate_fill', stroke='plate',
              width=1.6)
    if paths:
        first, last = paths[0], paths[-1]
        scene.add('polygon', points=[first[1], last[1], last[2], first[2]], fill='beam_zone')
        if first[5] and last[5]:
            scene.add('polygon', points=[first[2], last[2], last[5], first[5]], fill='beam_zone')

    # Wedge (or the water column) and the probe on it
    if has_wedge:
        if sin_a > 1e-6:
            h_at = lambda x: h1 + x * sin_a / cos_a
            outline = [(front, 0.0)]
            x_top = (height - h1) * cos_a / sin_a
            outline += [(front, -height), (x_top, -height)] if x_top < front else [(front, -h_at(front))]
            outline += [(back, -h_at(back)), (back, 0.0)] if h_at(back) > 0 else [(-h1 * cos_a / sin_a, 0.0)]
        else:
            outline = [(front, 0.0), (front, -height), (back, -height), (back, 0.0)]
        scene.add('polygon', points=outline, fill='water' if water else 'wedge_fill', stroke='wedge_line', width=1.4)
    margin = 1.0 / 25.4
    stand = 2.0 / 25.4
    p1, p2 = face(-margin - pitch / 2), face(array + margin + pitch / 2)
    nx, ny = -sin_a, -cos_a
    scene.add('polygon', points=[p1, p2, (p2[0] + nx * stand, p2[1] + ny * stand),
                                 (p1[0] + nx * stand, p1[1] + ny * stand)], fill='probe_fill', stroke='wedge_line',
              width=1.4)

    for (ex, ey), (sx, _), end, angle, drawn, skip in paths:
        if drawn:
            if has_wedge and ey < 0:
                scene.add('line', points=[(ex, ey), (sx, 0.0)], stroke='wedge_beam', width=1.0)
            scene.add('line', points=[(sx, 0.0), end] + ([skip] if skip else []), stroke='beam', width=1.3)

    size = 30
    # Thickness, at the right
    dim_x = x_hi + 0.12
    scene.add('line', points=[(dim_x, 0.0), (dim_x, t)], stroke='dimension', width=1.2)
    scene.add('arrow', tip=(dim_x, 0.0), towards=(dim_x, t), stroke='dimension')
    scene.add('arrow', tip=(dim_x, t), towards=(dim_x, 0.0), stroke='dimension')
    scene.add('text', at=(dim_x + 0.05, t / 2), text=f"Thickness {u.length(t / M_TO_IN)}{' (assumed)' if assumed else ''}", size=size,
              stroke='dimension', anchor='lm', halo=True)

    # What the beams cover: the linear scan's width or the sector's angles
    if paths:
        first, last = paths[0], paths[-1]
        angles = sorted({round(p[3], 1) for p in paths})
        if len(angles) == 1 and len(paths) > 1:
            y = t + 0.1
            scene.add('line', points=[(first[2][0], y), (last[2][0], y)], stroke='dimension', width=1.2)
            scene.add('arrow', tip=(first[2][0], y), towards=(last[2][0], y), stroke='dimension')
            scene.add('arrow', tip=(last[2][0], y), towards=(first[2][0], y), stroke='dimension')
            width = abs(last[1][0] - first[1][0]) / M_TO_IN
            scene.add('text', at=((first[2][0] + last[2][0]) / 2, y + 0.04),
                      text=f'{_num(angles[0], 1)}° linear, coverage {u.length(width)}', size=size,
                      stroke='dimension', anchor='mt', halo=True)
        else:
            for path in (first, last):
                at, anchor = ((path[5][0], -0.04), 'md') if path[5] else ((path[2][0], t + 0.05), 'mt')
                scene.add('text', at=at, text=f'{_num(path[3], 1)}°', size=size, stroke='beam', anchor=anchor,
                          halo=True)

    # Focus
    law = data.get('law', {})
    focus = _inch(law.get('focus_distance'))
    if focus and 0 < focus < t * 1.5 and law.get('focus_mode') in ('Depth', 'TrueDepth'):
        scene.add('dashed', a=(x_lo, focus), b=(x_hi, focus), stroke='centre_line', width=1.0)
        scene.add('text', at=(x_lo - 0.05, focus), text=f'Focus {u.length(focus / M_TO_IN)}', size=size,
                  stroke='centre_line', anchor='rm', halo=True)

    # Labels on the probe and wedge
    label = ' / '.join(v for v in (probe.get('model'), wedge.get('model')) if v)
    if label:
        scene.add('text', at=((p1[0] + p2[0]) / 2, min(p1[1], p2[1]) - stand - 0.05), text=label, size=size,
                  stroke='text', anchor='md', halo=True)
    if has_wedge and h1:
        scene.add('text', at=(front + 0.06, -h1), text=f'First element height {u.length(h1 / M_TO_IN)}',
                  size=size - 4, stroke='text', anchor='lm', halo=True)
    if not paths:
        scene.add('text', at=((x_lo + x_hi) / 2, t / 2), text='No focal laws in this group', size=size,
                  stroke='text', halo=True)

    # Bounds: the drawing plus room for the labels round it (text is a fixed size in pixels, so the
    # room depends on the scale), padded to the box's shape
    body = (x_lo, x_hi, -top, t)
    side_px, below_px, above_px = 13 * size, 2.6 * size, 2.2 * size
    scale = width_px / ((x_hi - x_lo) * 1.6)       # first guess, then refined with the bounds it gives
    for _ in range(4):
        x_lo, x_hi = body[0] - side_px / scale, body[1] + side_px / scale
        y_lo, y_hi = body[2] - above_px / scale, body[3] + below_px / scale
        if (y_hi - y_lo) / (x_hi - x_lo) < aspect:
            extra = aspect * (x_hi - x_lo) - (y_hi - y_lo)
            y_lo, y_hi = y_lo - extra / 2, y_hi + extra / 2
        else:
            extra = (y_hi - y_lo) / aspect - (x_hi - x_lo)
            x_lo, x_hi = x_lo - extra / 2, x_hi + extra / 2
        scale = width_px / (x_hi - x_lo)
    scene.x_min, scene.x_max, scene.y_min, scene.y_max = x_lo, x_hi, y_lo, y_hi
    return scene


def _clip(exit_point, end, skip, reach):
    """(end, skip) of a beam cut `reach` inches of sound path after its exit point."""
    def along(a, b, distance):
        d = math.dist(a, b)
        return b if d <= distance else (a[0] + (b[0] - a[0]) * distance / d, a[1] + (b[1] - a[1]) * distance / d)
    first = math.dist(exit_point, end)
    if reach <= first:
        return along(exit_point, end, reach), None
    return end, along(end, skip, reach - first) if skip else None


def _setup_thickness(setup):
    for name in ('specimen_thickness', 'tr_max'):
        try:
            value = float(str(getattr(setup, name, '') or '').split()[0])
        except (ValueError, IndexError):
            continue
        return value / 25.4 if getattr(setup, 'units', 'imperial') == 'metric' else value
    return None


# ── Laying out the sheet ──────────────────────────────────────────────────────────────────

def _font(size, bold=False):
    names = ('arialbd.ttf', 'Arial Bold.ttf', 'DejaVuSans-Bold.ttf') if bold else ('arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf')
    for name in names:
        for folder in ('', os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')):
            try:
                return ImageFont.truetype(os.path.join(folder, name) if folder else name, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _pt(points):
    return round(points * DPI / 72)


class _Sheet:
    """Draws the sheet's sections top-down on a canvas `width` pixels wide."""
    BODY, HEAD = 7.0, 8.5

    def __init__(self, width, height):
        self.width, self.pad = width, _pt(4)
        self.image = Image.new('RGB', (width, height), 'white')
        self.draw = ImageDraw.Draw(self.image)
        self.body, self.bold, self.head = _font(_pt(self.BODY)), _font(_pt(self.BODY), True), _font(_pt(self.HEAD), True)
        self.row = round(_pt(self.BODY) * 1.42)
        self.y = 0

    def fit(self, text, font, width):
        if self.draw.textlength(text, font=font) <= width:
            return text
        while text and self.draw.textlength(text + '…', font=font) > width:
            text = text[:-1]
        return text + '…'

    def heading(self, title, note=''):
        self.y += _pt(3)
        self.draw.text((self.pad, self.y), title, font=self.head, fill=INK)
        if note:
            self.draw.text((self.width - self.pad, self.y + _pt(1)), note, font=self.body, fill=LABEL, anchor='ra')
        self.y += round(_pt(self.HEAD) * 1.35)
        self.draw.line([(self.pad, self.y), (self.width - self.pad, self.y)], fill=RULE, width=_pt(0.6))
        self.y += _pt(2.5)

    def pairs(self, items, columns=3):
        inner = self.width - 2 * self.pad
        col = inner / columns
        label_w = col * 0.47
        rows = math.ceil(len(items) / columns)
        for i, (label, value) in enumerate(items):
            r, c = i % rows, i // rows     # fill down the columns, as the instrument's report does
            x, y = self.pad + c * col, self.y + r * self.row
            self.draw.text((x, y), self.fit(label, self.body, label_w - _pt(3)), font=self.body, fill=LABEL)
            self.draw.text((x + label_w, y), self.fit(str(value), self.bold, col - label_w - _pt(4)),
                           font=self.bold, fill=INK)
        self.y += rows * self.row + _pt(1)

    def table(self, headers, rows, x0=None, x1=None):
        x0 = self.pad if x0 is None else x0
        x1 = self.width - self.pad if x1 is None else x1
        col = (x1 - x0) / len(headers)
        top = self.y
        self.draw.rectangle([x0, top, x1, top + self.row], fill=HEAD_FILL)
        for j, h in enumerate(headers):
            self.draw.text((x0 + col * (j + 0.5), top + self.row / 2), h, font=self.bold, fill=INK, anchor='mm')
        for i, cells in enumerate(rows, start=1):
            for j, cell in enumerate(cells):
                self.draw.text((x0 + col * (j + 0.5), top + self.row * (i + 0.5)), self.fit(str(cell), self.body, col - _pt(4)),
                               font=self.body, fill=INK, anchor='mm')
        bottom = top + self.row * (len(rows) + 1)
        self.draw.rectangle([x0, top, x1, bottom], outline=TABLE_LINE, width=_pt(0.6))
        return bottom

    def tcg(self, rows):
        headers = ('Point', 'Position (true depth)', 'Gain')
        if len(rows) <= 4:
            self.y = self.table(headers, rows, self.pad, self.width * 0.55) + _pt(2)
            return
        half = math.ceil(len(rows) / 2)
        mid = self.width / 2
        a = self.table(headers, rows[:half], self.pad, mid - _pt(3))
        b = self.table(headers, rows[half:], mid + _pt(3), self.width - self.pad)
        self.y = max(a, b) + _pt(2)


def _content_height(data, system, width):
    probe = _Sheet(width, 10)
    _draw_sections(probe, data, system)
    return probe.y


def _draw_sections(sheet, data, system):
    title = ' · '.join(v for v in (data.get('group'), data.get('technique')) if v)
    note = '   '.join(v for v in (data.get('file'), data.get('date'),
                                   f"Calibrations: {data['calibrations']}" if data.get('calibrations') else '') if v)
    sheet.y = 0
    sheet.draw.text((sheet.pad, sheet.y), f'Setup: {title}' if title else 'Setup', font=sheet.head, fill=INK)
    sheet.draw.text((sheet.width - sheet.pad, sheet.y + _pt(1)), note, font=sheet.body, fill=LABEL, anchor='ra')
    sheet.y += round(_pt(sheet.HEAD) * 1.2)
    for title, kind, content in sections(data, system):
        sheet.heading(title)
        if kind == 'pairs':
            sheet.pairs(content)
        elif kind == 'table':
            headers, rows = content
            sheet.y = sheet.table(headers, rows) + _pt(2)
        elif kind == 'tcg':
            sheet.tcg(content)


def sheet_png(setup, width_in, height_in):
    """
    PNG bytes of the setup's sheet, laid out for a `width_in` × `height_in` box: the tables at the
    top, the drawing filling what's left (taller than the box when the tables leave too little, so
    the picture is then scaled down to fit). None when the setup has no .nde data.
    """
    data = load(setup)
    if data is None:
        return None
    system = getattr(setup, 'units', 'imperial')
    width = round(width_in * DPI)
    tables = _content_height(data, system, width)
    heading = round(_pt(_Sheet.HEAD) * 1.35) + _pt(6)
    drawing = max(round(height_in * DPI) - tables - heading, round(MIN_DRAWING_IN * DPI))
    sheet = _Sheet(width, tables + heading + drawing)
    _draw_sections(sheet, data, system)
    sheet.heading('Scan Plan', 'Probe, wedge and beams from the .nde file')

    drawing_width = width - 2 * sheet.pad
    drawing = sheet.image.height - sheet.y - sheet.pad
    scene = drawing_scene(data, setup, drawing / drawing_width, system, drawing_width)
    picture = Image.open(io.BytesIO(render_scene(scene, drawing_width)))
    picture = picture.resize((drawing_width, drawing), Image.LANCZOS) if picture.size != (drawing_width, drawing) else picture
    sheet.image.paste(picture, (sheet.pad, sheet.y))

    out = io.BytesIO()
    sheet.image.save(out, format='PNG', optimize=True, dpi=(DPI, DPI))
    return out.getvalue()
