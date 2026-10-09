"""
The vessel drawing as a list of shapes in drawing units (the diameter is 100 across; y grows
downwards), in drawing order: supports and boot, the shell and heads, coverage shading, flanges,
seams, nozzles, then the numbered seam callouts, nozzle tags and the caption. Shapes name a style
(outline, coverage, ...) that render.py turns into a colour.

Shape kinds: polygon (points, fill, stroke, width), line (points, stroke, width), dashed (points,
stroke, width), circle (at, radius, fill, stroke, width), text (at, text, size, colour, anchor,
bold, halo).

Coverage marks (a report's, inches along the shell from the start tangent line):
  {'kind': 'part', 'target': 'start' | 'end' | 'boot' | course row number (0 = first)}
  {'kind': 'seam', 'target': seam number}
  {'kind': 'nozzle', 'target': tag}
  {'kind': 'band', 'start', 'end', 'from', 'to', 'style': 'solid' | 'grid', 'label'}
      from / to: directions round the shell (blank = all the way round)
  {'kind': 'box', 'start', 'end', 'label'}
"""
import math
import re
from dataclasses import dataclass, field

from .lengths import format_diameter, format_length
from .layout import build_layout, head_profile
from .spec import BOOT, BOTTOM, END_HEAD, SHELL, START_HEAD, alpha, band_alphas, ends

PX_PER_UNIT = 2.4                  # the PNG's pixels per drawing unit (a 100-unit diameter is 240 px)
TEXT = 13                          # px
SEAM_RADIUS = 6.0
TAG_HEIGHT = 12.0
LANE_GAP = 14.0
MARGIN = 8.0
SIZE = re.compile(r'\d*\.?\d+')


@dataclass
class Scene:
    x_min: float = 0.0
    x_max: float = 0.0
    y_min: float = 0.0
    y_max: float = 0.0
    shapes: list = field(default_factory=list)

    def add(self, kind, **values):
        self.shapes.append({'kind': kind, **values})


def text_width(text, size=TEXT):
    """Rough width of `text` in drawing units (Arial averages ~0.58 em a character)."""
    return len(str(text)) * size * 0.58 / PX_PER_UNIT


class _Builder:
    def __init__(self, spec, coverage):
        self.spec = spec
        self.coverage = list(coverage or [])
        self.layout = build_layout(spec)
        self.scene = Scene()
        self.horizontal = spec.horizontal
        self.tank = spec.vessel_type == 'tank'
        self.extent = []        # local (s, r) points of everything drawn, for the label lanes
        self.labels = []        # nozzle tags waiting for a lane
        self.nozzle_marks = {}  # tag -> highlight shapes (coverage)
        self.faces = []         # [(s, r, radius)] nozzles facing the viewer: seam numbers keep clear of them

    # ── coordinates ──────────────────────────────────────────────────
    def p(self, s, r):
        """Screen point of a local (s along the axis, r off the centre line)."""
        return (s, -r) if self.horizontal else (r, -s)

    def pts(self, points):
        return [self.p(s, r) for s, r in points]

    def keep(self, points):
        self.extent.extend(points)
        return points

    # ── the vessel ───────────────────────────────────────────────────
    def outline(self):
        """The shell and welded heads as one closed outline [(s, r)]."""
        top = []
        for seg in self.layout.segments:
            if seg.kind == 'head':
                if seg.bolted:
                    continue
                profile = head_profile(seg, self.tank)
                top.extend(reversed(profile) if seg.end == 'start' else profile)
            else:
                top.extend([(seg.s0, seg.r0), (seg.s1, seg.r1)])
        bottom = [(s, -r) for s, r in reversed(top)]
        return top + bottom

    def part_polygon(self, seg):
        if seg.kind == 'head':
            if seg.bolted:
                return self.cover_polygon(seg)
            profile = head_profile(seg, self.tank)
            return profile + [(s, -r) for s, r in reversed(profile)]
        return [(seg.s0, seg.r0), (seg.s1, seg.r1), (seg.s1, -seg.r1), (seg.s0, -seg.r0)]

    def cover_polygon(self, seg):
        r = seg.r0 * (1 + 2 * 0.09)
        return [(seg.s0, r), (seg.s1, r), (seg.s1, -r), (seg.s0, -r)]

    def supports(self):
        lay, kind = self.layout, self.spec.supports
        if kind == 'auto':
            kind = {'horizontal': 'saddles', 'exchanger': 'saddles', 'vertical': 'skirt', 'tank': 'none'}[
                self.spec.vessel_type]
        if kind == 'none':
            if self.tank:   # the ground under a tank
                s = lay.segments[0].s0
                r = lay.max_radius() + 14
                self.scene.add('line', points=self.pts([(s - 1, -r), (s - 1, r)]), stroke='outline', width=1.6)
            return
        r_max = lay.max_radius()
        if self.horizontal:
            body = lay.body()
            if self.spec.vessel_type == 'exchanger':
                # Under the shell: past the first flange that follows a course (the channel's)
                first = lay.tl_start
                for seg in lay.segments:
                    if seg.kind == 'flange' and seg.s0 > lay.tl_start + 1 and seg.s1 < (lay.tl_start + lay.tl_end) / 2:
                        first = seg.s1
                        break
                spots = [first + 0.18 * (lay.tl_end - first), lay.tl_end - 0.15 * (lay.tl_end - first)]
            else:
                spots = [lay.tl_start + 0.2 * (lay.tl_end - lay.tl_start), lay.tl_end - 0.2 * (lay.tl_end - lay.tl_start)]
            if not body:
                return
            for s in spots:
                r = lay.radius_at(s)
                if kind == 'legs':
                    leg = [(s - 3, -r * 0.6), (s + 3, -r * 0.6), (s + 3, -r - 30), (s - 3, -r - 30)]
                    foot = [(s - 7, -r - 30), (s + 7, -r - 30), (s + 7, -r - 33), (s - 7, -r - 33)]
                    for shape in (leg, foot):
                        self.scene.add('polygon', points=self.pts(self.keep(shape)), fill='support', stroke='outline', width=1.2)
                else:
                    # A saddle: its web tapering down from the shell to the base plate
                    web = [(s - 11, -r * 0.97), (s + 11, -r * 0.97), (s + 8, -r - 20), (s - 8, -r - 20)]
                    base = [(s - 13, -r - 20), (s + 13, -r - 20), (s + 13, -r - 23), (s - 13, -r - 23)]
                    for shape in (web, base):
                        self.scene.add('polygon', points=self.pts(self.keep(shape)), fill='support', stroke='outline', width=1.2)
            return
        start = lay.segments[0]
        r = lay.body()[0].r0 if lay.body() else r_max
        bottom = start.s0 - 0.45 * 2 * r
        if kind == 'legs':
            for side in (-1, 1):
                leg = [(lay.tl_start + 0.1 * 2 * r, side * r), (lay.tl_start + 0.1 * 2 * r, side * (r + 5)),
                       (bottom, side * (r + 5)), (bottom, side * r)]
                self.scene.add('polygon', points=self.pts(self.keep(leg)), fill='paper', stroke='outline', width=1.2)
                foot = [(bottom, side * (r - 3)), (bottom, side * (r + 9)), (bottom - 3, side * (r + 9)), (bottom - 3, side * (r - 3))]
                self.scene.add('polygon', points=self.pts(self.keep(foot)), fill='paper', stroke='outline', width=1.2)
        else:   # skirt from the bottom tangent line down past the head, with its base ring
            skirt = [(lay.tl_start, r), (bottom, r), (bottom, -r), (lay.tl_start, -r)]
            self.scene.add('polygon', points=self.pts(self.keep(skirt)), fill='paper', stroke='outline', width=1.4)
            ring = [(bottom, r + 5), (bottom + 3, r + 5), (bottom + 3, -r - 5), (bottom, -r - 5)]
            self.scene.add('polygon', points=self.pts(self.keep(ring)), fill='paper', stroke='outline', width=1.2)
            access = (bottom + (lay.tl_start - bottom) * 0.35, 0.55 * r)
            self.scene.add('circle', at=self.p(*access), radius=min(9, r * 0.2), fill=None, stroke='outline', width=1.0)

    def boot(self):
        """A horizontal vessel's boot: its shell and head below the vessel, behind the shell outline."""
        spec, lay = self.spec, self.layout
        if not spec.has_boot:
            return None
        s = lay.s_at(spec.boot_position if spec.boot_position is not None else lay.length / 2)
        rb = spec.boot_diameter * lay.scale / 2
        length = min(spec.boot_length * lay.scale, 1.3 * 100)
        top = -lay.radius_at(s) * 0.9
        tl = -lay.radius_at(s) - length
        depth = rb / 2
        profile = [(s + rb * math.cos(t), tl - depth * math.sin(t))
                   for t in (math.pi * k / 24 for k in range(25))]
        shape = [(s - rb, top), (s + rb, top)] + profile
        boot = {'s': s, 'rb': rb, 'top': -lay.radius_at(s), 'tl': tl, 'apex': tl - depth, 'polygon': shape,
                'scale': length / spec.boot_length}
        self.scene.add('polygon', points=self.pts(self.keep(shape)), fill='paper', stroke='outline', width=1.6)
        return boot

    def flanges(self):
        for seg in self.layout.segments:
            if seg.kind == 'flange':
                r = seg.r0 * (1 + 2 * 0.09)
                rect = [(seg.s0, r), (seg.s1, r), (seg.s1, -r), (seg.s0, -r)]
                self.scene.add('polygon', points=self.pts(self.keep(rect)), fill='flange', stroke='outline', width=1.6)
                mid = (seg.s0 + seg.s1) / 2
                self.scene.add('line', points=self.pts([(mid, r), (mid, -r)]), stroke='outline', width=1.0)
            elif seg.kind == 'head' and seg.bolted:
                self.scene.add('polygon', points=self.pts(self.keep(self.cover_polygon(seg))), fill='flange',
                               stroke='outline', width=1.6)

    def seam_list(self):
        """Welded joints along the vessel, start to end: [(s, r)]."""
        segs = self.layout.segments
        joints = []
        for a, b in zip(segs, segs[1:]):
            bolted = (a.kind == 'head' and a.bolted and b.kind == 'flange') or \
                     (b.kind == 'head' and b.bolted and a.kind == 'flange')
            if bolted:
                continue
            if a.kind == 'head' and a.head == 'flat' and self.tank:
                joints.append((a.s1, b.r0))       # a tank's shell-to-bottom weld
                continue
            r = b.r0 if b.kind != 'flange' else a.r1
            joints.append((a.s1, r))
        return joints

    # ── nozzles ──────────────────────────────────────────────────────
    def neck(self, size):
        match = SIZE.search(str(size or ''))
        inches = float(match.group()) if match else 4.0
        if self.spec.metric and inches > 40:      # a DN size: millimetres
            inches /= 25.4
        return max(2.5, min(17.5, inches * self.layout.scale / 2))

    def side_nozzle(self, tag, s, base, sign, hw, along_s=True, colour='outline'):
        """A nozzle neck standing out of a surface at r = base (sign: which way), its flange at the tip."""
        ext = max(10.0, 1.2 * hw) + 4
        tip = base + sign * ext
        if along_s:
            neck = [(s - hw, base), (s + hw, base), (s + hw, tip), (s - hw, tip)]
            flange = [(s - hw - 2.5, tip), (s + hw + 2.5, tip), (s + hw + 2.5, tip - sign * 2.5),
                      (s - hw - 2.5, tip - sign * 2.5)]
            ring = [(s - hw - 2, base), (s + hw + 2, base)]
        else:   # the neck runs along s (a head's nozzle, or a boot's side nozzle): s and r swap roles
            neck = [(base, s - hw), (base, s + hw), (tip, s + hw), (tip, s - hw)]
            flange = [(tip, s - hw - 2.5), (tip, s + hw + 2.5), (tip - sign * 2.5, s + hw + 2.5),
                      (tip - sign * 2.5, s - hw - 2.5)]
            ring = [(base, s - hw - 2), (base, s + hw + 2)]
        for shape in (neck, flange):
            self.scene.add('polygon', points=self.pts(self.keep(shape)), fill='paper', stroke=colour, width=1.4)
        self.nozzle_marks[tag] = [{'kind': 'line', 'points': self.pts(ring), 'stroke': 'coverage_line', 'width': 4.0}]
        return (s, tip) if along_s else (tip, s)

    def face_nozzle(self, tag, s, r, hw, near):
        radius = max(3.0, hw)
        self.faces.append((s, r, radius))
        if near:
            self.scene.add('circle', at=self.p(s, r), radius=radius, fill='paper', stroke='outline', width=1.4)
            self.scene.add('circle', at=self.p(s, r), radius=0.9, fill='outline', stroke=None, width=0)
        else:
            self.scene.add('circle', at=self.p(s, r), radius=radius, fill=None, stroke='hidden', width=1.2,
                           dashed=True)
        self.nozzle_marks[tag] = [{'kind': 'circle', 'at': self.p(s, r), 'radius': radius + 2.5, 'fill': None,
                                   'stroke': 'coverage_line', 'width': 3.0}]
        return (s, r)

    def head_surface(self, seg, r):
        """s on a head's outline at distance r off the centre line."""
        if seg.bolted:
            return seg.s0 if seg.end == 'start' else seg.s1
        profile = head_profile(seg, self.tank)
        r = abs(r)
        for (s0, r0), (s1, r1) in zip(profile, profile[1:]):
            if min(r0, r1) - 1e-9 <= r <= max(r0, r1) + 1e-9 and abs(r0 - r1) > 1e-9:
                return s0 + (s1 - s0) * (r - r0) / (r1 - r0)
        return profile[-1][0]

    def nozzles(self, boot):
        spec, lay = self.spec, self.layout
        heads = {seg.end: seg for seg in lay.segments if seg.kind == 'head'}
        for nozzle in spec.nozzles:
            tag = str(nozzle.get('tag') or '').strip()
            location = nozzle.get('location') or SHELL
            hw = self.neck(nozzle.get('size'))
            position = nozzle.get('position')
            if location in (START_HEAD, END_HEAD):
                seg = heads[location]
                offset = max(-0.8, min(0.8, (position or 0) * lay.scale / seg.r0)) * seg.r0
                sign = -1 if location == START_HEAD else 1
                base = self.head_surface(seg, offset)
                tip = self.side_nozzle(tag, offset, base, sign, hw, along_s=False)
                lane = 's-' if location == START_HEAD else 's+'
                self.labels.append((tag, lane, tip))
                continue
            if location == BOOT:
                if boot is None:
                    continue
                direction = nozzle.get('direction') or BOTTOM
                if direction == BOTTOM:
                    tip = self.side_nozzle(tag, boot['s'], boot['apex'] + 1, -1, hw)
                    self.labels.append((tag, 'r-', tip))
                    continue
                a = alpha(spec, direction, BOOT)
                if a is None:
                    continue
                r = boot['top'] - (position or 0) * boot['scale']
                r = max(boot['tl'] + hw, min(boot['top'] - hw, r))
                lateral = math.cos(math.radians(a))
                if abs(lateral) >= 0.38:
                    sign = 1 if lateral > 0 else -1
                    tip = self.side_nozzle(tag, r, boot['s'] + sign * boot['rb'], sign, hw, along_s=False)
                else:
                    tip = self.face_nozzle(tag, boot['s'] + boot['rb'] * lateral, r, hw,
                                           math.sin(math.radians(a)) > 0)
                self.labels.append((tag, 'r-', tip))
                continue
            a = alpha(spec, nozzle.get('direction'), SHELL)
            if a is None:
                continue
            s = lay.s_at(position or 0)
            s = max(lay.tl_start + hw, min(lay.tl_end - hw, s))
            r = lay.radius_at(s)
            lateral = math.cos(math.radians(a))
            if abs(lateral) >= 0.38:
                sign = 1 if lateral > 0 else -1
                tip = self.side_nozzle(tag, s, sign * r, sign, hw)
                self.labels.append((tag, 'r+' if sign > 0 else 'r-', tip))
            else:
                offset = max(-(r - hw), min(r - hw, r * lateral))
                tip = self.face_nozzle(tag, s, offset, hw, math.sin(math.radians(a)) > 0)
                self.labels.append((tag, 'r+' if lateral > 0.05 else 'r-', tip))

    # ── coverage ─────────────────────────────────────────────────────
    def coverage_fills(self, boot):
        lay = self.layout
        for mark in self.coverage:
            kind = mark.get('kind')
            if kind == 'part':
                target = mark.get('target')
                polygon = None
                if target in ('start', 'end'):
                    seg = next((x for x in lay.segments if x.kind == 'head' and x.end == target), None)
                    polygon = self.part_polygon(seg) if seg else None
                elif target == 'boot' and boot:
                    polygon = boot['polygon']
                else:
                    try:
                        index = int(target)
                    except (TypeError, ValueError):
                        continue
                    seg = next((x for x in lay.segments if x.index == index and x.kind != 'flange'), None)
                    polygon = self.part_polygon(seg) if seg else None
                if polygon:
                    self.scene.add('polygon', points=self.pts(polygon), fill='coverage', stroke=None, width=0)
            elif kind == 'band':
                self.band(mark)

    def band(self, mark):
        lay = self.layout
        s0, s1 = lay.s_at(mark.get('start') or 0), lay.s_at(mark.get('end') if mark.get('end') is not None else lay.length)
        if s1 < s0:
            s0, s1 = s1, s0
        if s1 - s0 < 1:
            s1 = s0 + 1
        a, b = band_alphas(self.spec, mark.get('from'), mark.get('to'))
        steps = [a + (b - a) * k / 90 for k in range(91)]
        seen = [math.cos(math.radians(x)) for x in steps if math.sin(math.radians(x)) > 1e-6]
        far = not seen
        values = seen or [math.cos(math.radians(x)) for x in steps]
        low, high = min(values), max(values)
        if b - a >= 359.9:
            low, high, far = -1.0, 1.0, False
        n = max(2, int((s1 - s0) / 4))
        ss = [s0 + (s1 - s0) * k / n for k in range(n + 1)]
        polygon = [(s, lay.radius_at(s) * high) for s in ss] + [(s, lay.radius_at(s) * low) for s in reversed(ss)]
        if far:
            self.scene.add('polygon', points=self.pts(polygon), fill=None, stroke='coverage_line', width=1.6, dashed=True)
        else:
            self.scene.add('polygon', points=self.pts(polygon), fill='coverage', stroke=None, width=0)
        mark['_polygon'] = polygon
        mark['_far'] = far
        mark['_lateral'] = (low, high)
        mark['_s'] = (s0, s1)

    def coverage_marks(self):
        lay = self.layout
        for mark in self.coverage:
            kind = mark.get('kind')
            if kind == 'band' and '_polygon' in mark:
                s0, s1 = mark['_s']
                low, high = mark['_lateral']
                if mark.get('style') == 'grid':
                    s = s0
                    while s <= s1 + 1e-6:
                        r = lay.radius_at(s)
                        self.scene.add('line', points=self.pts([(s, r * low), (s, r * high)]), stroke='coverage_line', width=1.0)
                        s += 8
                    r_ref = lay.radius_at(s0)
                    level = low
                    while level <= high + 1e-6:
                        self.scene.add('line', points=self.pts([(s0, lay.radius_at(s0) * level), (s1, lay.radius_at(s1) * level)]),
                                       stroke='coverage_line', width=1.0)
                        level += 8 / max(r_ref, 1)
                if not mark['_far']:
                    self.scene.add('polygon', points=self.pts(mark['_polygon']), fill=None, stroke='coverage_line', width=1.4)
                label = str(mark.get('label') or '').strip()
                if label or mark['_far']:
                    text = label + (' (far side)' if mark['_far'] else '')
                    mid = ((s0 + s1) / 2, lay.radius_at((s0 + s1) / 2) * (low + high) / 2)
                    self.scene.add('text', at=self.p(*mid), text=text.strip(), size=11, colour='coverage_text',
                                   anchor='mm', bold=True, halo=True)
            elif kind == 'seam':
                for number, (s, r) in self.numbered_seams():
                    if str(number) == str(mark.get('target')).strip():
                        self.scene.add('line', points=self.pts([(s, r), (s, -r)]), stroke='coverage_line', width=4.5)
            elif kind == 'nozzle':
                for shape in self.nozzle_marks.get(str(mark.get('target') or '').strip(), []):
                    self.scene.shapes.append(dict(shape))

    def boxes(self):
        lay = self.layout
        r = lay.max_radius() + 8
        for mark in self.coverage:
            if mark.get('kind') != 'box':
                continue
            s0 = lay.s_at(mark.get('start') or 0)
            s1 = lay.s_at(mark.get('end') if mark.get('end') is not None else lay.length)
            if s1 < s0:
                s0, s1 = s1, s0
            s0, s1 = s0 - 4, s1 + 4
            rect = [(s0, r), (s1, r), (s1, -r), (s0, -r)]
            self.scene.add('polygon', points=self.pts(self.keep(rect)), fill=None, stroke='box', width=2.6)
            label = str(mark.get('label') or '').strip()
            if label:
                corners = self.pts(rect)
                x = min(x for x, _ in corners)
                y = min(y for _, y in corners)
                self.scene.add('text', at=(x + 2, y - 2), text=label, size=13, colour='box', anchor='ld', bold=True)
                self.extent.append(self.local((x + 2 + text_width(label, 13), y - 8)))

    def local(self, point):
        """The local (s, r) of a screen point."""
        x, y = point
        return (x, -y) if self.horizontal else (-y, x)

    # ── numbers and tags ─────────────────────────────────────────────
    def numbered_seams(self):
        first = self.spec.seam_start or 1
        return [(first + i, joint) for i, joint in enumerate(self.seam_list())]

    def seam_callouts(self, boot):
        lay = self.layout
        numbered = self.numbered_seams()
        for number, (s, r) in numbered:
            self.scene.add('line', points=self.pts([(s, r), (s, -r)]), stroke='outline', width=1.2)
        boot_seams = []
        if boot:
            n = (self.spec.seam_start or 1) + len(numbered)
            boot_seams = [(n, (boot['s'], boot['top'] - 4)), (n + 1, (boot['s'], boot['tl']))]
            self.scene.add('line', points=self.pts([(boot['s'] - boot['rb'], boot['tl']), (boot['s'] + boot['rb'], boot['tl'])]),
                           stroke='outline', width=1.2)
        taken = list(self.faces)
        for number, (s, r) in numbered:
            # On the centre line, unless a nozzle facing the viewer or the seam number before is there
            for k in (0, 0.5, -0.5, 0.75, -0.75):
                offset = k * r
                if all(math.hypot(s - fs, offset - fr) > fradius + SEAM_RADIUS + 1.5 for fs, fr, fradius in taken):
                    break
            taken.append((s, offset, SEAM_RADIUS))
            self.callout(self.p(s, offset), number, self.seam_covered(number))
        for number, (s, r) in boot_seams:
            self.callout(self.p(s, r), number, self.seam_covered(number))
        # Course labels (e.g. Channel), under the centre line
        for seg in lay.segments:
            if seg.kind == 'course' and seg.label:
                self.scene.add('text', at=self.p((seg.s0 + seg.s1) / 2, -0.45 * seg.r0), text=seg.label, size=11,
                               colour='label', anchor='mm', bold=False, halo=True)

    def seam_covered(self, number):
        return any(m.get('kind') == 'seam' and str(m.get('target')).strip() == str(number) for m in self.coverage)

    def callout(self, at, number, covered=False):
        self.scene.add('circle', at=at, radius=SEAM_RADIUS, fill='coverage' if covered else 'paper', stroke='seam', width=1.3)
        self.scene.add('text', at=at, text=str(number), size=12, colour='seam', anchor='mm', bold=False)

    def tags(self):
        """Each nozzle's tag in a hexagon, in a lane beyond the vessel on its side, with a leader."""
        if not self.labels:
            return
        s_values = [s for s, _ in self.extent]
        r_values = [r for _, r in self.extent]
        lanes = {
            'r+': max(r_values) + LANE_GAP,
            'r-': min(r_values) - LANE_GAP,
            's-': min(s_values) - LANE_GAP,
            's+': max(s_values) + LANE_GAP,
        }
        grouped = {}
        for tag, lane, tip in self.labels:
            grouped.setdefault(lane, []).append((tag, tip))
        for lane, items in grouped.items():
            along_s = lane in ('r+', 'r-')
            items.sort(key=lambda item: item[1][0] if along_s else item[1][1])
            placed = []
            for tag, tip in items:
                width = max(TAG_HEIGHT * 1.15, text_width(tag) + 7)
                size = self.screen_size(width, along_s)
                want = tip[0] if along_s else tip[1]
                if placed:
                    prev_pos, prev_size = placed[-1][2], placed[-1][3]
                    want = max(want, prev_pos + prev_size / 2 + size / 2 + 2)
                placed.append((tag, tip, want, size, width))
            # Pull the row back so it sits centred on the nozzles it labels
            if len(placed) > 1:
                shift = (sum(p[2] for p in placed) - sum((p[1][0] if along_s else p[1][1]) for p in placed)) / len(placed)
                placed = [(t, tip, pos - shift, size, w) for t, tip, pos, size, w in placed]
            for tag, tip, pos, size, width in placed:
                if along_s:   # half the tag's extent across the lane: its height, or its width on a vertical vessel
                    half = TAG_HEIGHT / 2 if self.horizontal else width / 2
                    centre = (pos, lanes[lane] + (half if lane == 'r+' else -half))
                else:
                    edge = lanes[lane]
                    centre = (edge + (-1 if lane == 's-' else 1) * self.axis_half(width), pos)
                self.tag(tag, tip, centre, width)

    def screen_size(self, width, along_s):
        """A tag's extent along its lane: its width when the lane runs across the screen."""
        across = (along_s and self.horizontal) or (not along_s and not self.horizontal)
        return width if across else TAG_HEIGHT

    def axis_half(self, width):
        """Half a tag's extent along the vessel's axis direction on screen."""
        return width / 2 if self.horizontal else TAG_HEIGHT / 2

    def tag(self, text, tip, centre, width):
        cx, cy = self.p(*centre)
        tx, ty = self.p(*tip)
        h = TAG_HEIGHT / 2
        w = width / 2
        hexagon = [(cx - w, cy), (cx - w + h * 0.55, cy - h), (cx + w - h * 0.55, cy - h), (cx + w, cy),
                   (cx + w - h * 0.55, cy + h), (cx - w + h * 0.55, cy + h)]
        # Leader from the nozzle's flange to the hexagon's nearest edge
        dx, dy = cx - tx, cy - ty
        distance = math.hypot(dx, dy) or 1
        end = (cx - dx / distance * min(w, h * 1.1), cy - dy / distance * h * 1.1) if abs(dy) > abs(dx) \
            else (cx - math.copysign(w, dx), cy)
        self.scene.add('line', points=[(tx, ty), end], stroke='leader', width=1.0)
        covered = any(m.get('kind') == 'nozzle' and str(m.get('target')).strip() == text for m in self.coverage)
        self.scene.add('polygon', points=hexagon, fill='coverage' if covered else 'paper', stroke='outline', width=1.2)
        self.scene.add('text', at=(cx, cy), text=text, size=TEXT, colour='text', anchor='mm', bold=False)

    def caption(self):
        """Under the drawing: the size, and an arrow naming the compass direction it points."""
        spec, lay = self.spec, self.layout
        xs = [x for shape in self.scene.shapes for x, _ in _points(shape)]
        ys = [y for shape in self.scene.shapes for _, y in _points(shape)]
        x0, y1 = min(xs), max(ys) + 16
        size = f'{format_diameter(spec.diameter, spec.metric)} {spec.diameter_basis} × {format_length(lay.length, spec.metric)} T/T'
        if self.horizontal:
            left, _ = ends(spec)
            arrow_text, pointing = left, -1
        else:
            _, right = ends(spec)
            arrow_text, pointing = right, 1
        a0, a1 = x0, x0 + 34
        tip, tail = (a0, y1) if pointing < 0 else (a1, y1), (a1, y1) if pointing < 0 else (a0, y1)
        self.scene.add('line', points=[tail, tip], stroke='outline', width=1.6)
        head = [tip, (tip[0] - pointing * 7, y1 - 3.2), (tip[0] - pointing * 7, y1 + 3.2)]
        self.scene.add('polygon', points=head, fill='outline', stroke='outline', width=1.0)
        label_x = a0 - 3 if pointing < 0 else a1 + 3
        self.scene.add('text', at=(label_x, y1), text=arrow_text, size=15, colour='text',
                       anchor='rm' if pointing < 0 else 'lm', bold=True)
        note_x = a1 + 12 if pointing < 0 else a1 + 12 + text_width(arrow_text, 15)
        self.scene.add('text', at=(note_x, y1), text=f'{size}  ·  viewed from {spec.view_from}', size=12,
                       colour='label', anchor='lm', bold=False)
        if pointing < 0:
            self.scene.shapes.append({'kind': 'bounds', 'points': [(a0 - 3 - text_width(arrow_text, 15), y1 - 8)]})
        self.scene.shapes.append({'kind': 'bounds', 'points': [(note_x + text_width(f'{size}  ·  viewed from {spec.view_from}', 12), y1 + 8)]})

    def centre_line(self):
        lay = self.layout
        s0, s1 = lay.segments[0].s0 - 8, lay.segments[-1].s1 + 8
        self.scene.add('dashed', points=self.pts([(s0, 0), (s1, 0)]), stroke='centre', width=0.9)

    def build(self):
        self.supports()
        boot = self.boot()
        body = self.keep(self.outline())
        self.scene.add('polygon', points=self.pts(body), fill='paper', stroke=None, width=0)
        self.coverage_fills(boot)
        self.scene.add('polygon', points=self.pts(body), fill=None, stroke='outline', width=1.8)
        if boot:   # the boot's opening into the shell, drawn over the shell's bottom edge
            s, rb, top = boot['s'], boot['rb'], boot['top']
            self.scene.add('line', points=self.pts([(s - rb, top), (s - rb, top - 4)]), stroke='outline', width=1.6)
            self.scene.add('line', points=self.pts([(s + rb, top), (s + rb, top - 4)]), stroke='outline', width=1.6)
        self.flanges()
        self.centre_line()
        self.nozzles(boot)
        self.coverage_marks()
        self.seam_callouts(boot)
        self.boxes()
        self.tags()
        self.caption()
        return self.scene


def _points(shape):
    kind = shape['kind']
    if kind in ('polygon', 'line', 'dashed', 'bounds'):
        return shape['points']
    if kind == 'circle':
        (x, y), r = shape['at'], shape['radius']
        return [(x - r, y - r), (x + r, y + r)]
    if kind == 'text':
        x, y = shape['at']
        w = text_width(shape['text'], shape['size'])
        h = shape['size'] / PX_PER_UNIT
        anchor = shape.get('anchor', 'mm')
        left = x - w / 2 if anchor[0] == 'm' else (x - w if anchor[0] == 'r' else x)
        top = y - h / 2 if anchor[1] == 'm' else (y - h if anchor[1] in ('d', 's') else y)
        return [(left, top), (left + w, top + h)]
    return []


def build_scene(spec, coverage=()):
    """The drawing of `spec` (a VesselSpec) with the report's coverage marks, bounds set."""
    scene = _Builder(spec, [dict(m) for m in coverage or []]).build()
    xs = [x for shape in scene.shapes for x, _ in _points(shape)]
    ys = [y for shape in scene.shapes for _, y in _points(shape)]
    scene.x_min, scene.x_max = min(xs) - MARGIN, max(xs) + MARGIN
    scene.y_min, scene.y_max = min(ys) - MARGIN, max(ys) + MARGIN
    scene.shapes = [shape for shape in scene.shapes if shape['kind'] != 'bounds']
    return scene
