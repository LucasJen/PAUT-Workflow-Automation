"""
A vessel laid out along its axis for the schematic drawing, like the client's FHR sheets:
proportional but not to scale. The diameter is always drawn 100 units across; a long vessel's
length is squeezed so it stays within a few diameters, and short courses are widened so their seam
numbers fit. Positions typed in inches along the shell (from the start tangent line) are mapped
onto the drawing through the segments.

Axis coordinate s runs from the start end (left on a horizontal vessel, the bottom on a vertical
one) to the other; r is the distance off the centre line. Everything here is in drawing units.
"""
from dataclasses import dataclass, field

DRAWN_DIAMETER = 100.0
# A vessel's shell is drawn at most this many diameters long (horizontal / vertical)
MAX_RATIO = {'horizontal': 5.0, 'exchanger': 5.0, 'vertical': 4.5, 'tank': 3.0}
MIN_COURSE = 24.0      # drawing units: room for the seam numbers either end
MIN_CONE = 12.0
FLANGE_WIDTH = 0.09    # of the diameter beside it
FLANGE_OVERHANG = 0.09
COVER_WIDTH = 0.06     # a bolted flat cover

HEAD_DEPTH = {          # drawn depth as a fraction of the diameter
    'ellipsoidal': 0.25, 'hemispherical': 0.5, 'torispherical': 0.19, 'cone': 0.45, 'flat': 0.04,
    'dome': 0.1,
}
TANK_HEAD_DEPTH = {'cone': 0.08, 'dome': 0.1, 'flat': 0.03}


@dataclass
class Segment:
    kind: str            # head, course, cone, flange
    s0: float
    s1: float
    r0: float            # radius at s0 / s1 (a flange: the radius of the shell beside it)
    r1: float
    l0: float = 0.0      # inches along the shell from the start tangent line (heads: their tangent line)
    l1: float = 0.0
    index: int = -1      # the course row it comes from (-1: a head or an automatic cone)
    end: str = ''        # heads: 'start' / 'end'
    head: str = ''       # heads: the head type
    bolted: bool = False  # heads: a flat cover bolted to a flange
    label: str = ''


@dataclass
class Layout:
    segments: list = field(default_factory=list)
    scale: float = 1.0          # drawing units per inch across the vessel
    axial: float = 1.0          # drawing units per inch along it (squeezed)
    length: float = 0.0         # inches, tangent line to tangent line
    tl_start: float = 0.0       # s of the start / end tangent lines
    tl_end: float = 0.0

    def body(self):
        return [seg for seg in self.segments if seg.kind in ('course', 'cone')]

    def radius_at(self, s):
        """The shell's drawn radius at s (between the tangent lines)."""
        for seg in self.body():
            if seg.s0 - 1e-6 <= s <= seg.s1 + 1e-6:
                if seg.s1 - seg.s0 < 1e-9:
                    return seg.r0
                return seg.r0 + (seg.r1 - seg.r0) * (s - seg.s0) / (seg.s1 - seg.s0)
        return self.body()[-1].r1 if s > self.tl_end else self.body()[0].r0

    def s_at(self, inches):
        """The drawn s of a position `inches` along the shell from the start tangent line."""
        body = self.body()
        if inches is None:
            return None
        for seg in body:
            if seg.l0 - 1e-9 <= inches <= seg.l1 + 1e-9 and seg.l1 - seg.l0 > 1e-9:
                return seg.s0 + (seg.s1 - seg.s0) * (inches - seg.l0) / (seg.l1 - seg.l0)
        if inches <= 0:
            return self.tl_start
        return self.tl_end

    def max_radius(self):
        return max(max(seg.r0, seg.r1) for seg in self.segments)


def _head_depth(head, diameter, tank):
    table = TANK_HEAD_DEPTH if tank else HEAD_DEPTH
    return table.get(head, HEAD_DEPTH.get(head, 0.25)) * diameter


def build_layout(spec):
    """The vessel's segments end to end (heads included) and the inch-to-drawing scales."""
    scale = DRAWN_DIAMETER / spec.diameter
    tank = spec.vessel_type == 'tank'
    rows = [row for row in spec.courses if row.get('kind') in ('course', 'cone', 'flange')]
    length = sum(row.get('length') or 0 for row in rows if row.get('kind') != 'flange')
    ratio = MAX_RATIO.get(spec.vessel_type, 5.0)
    axial = min(scale, ratio * DRAWN_DIAMETER / length) if length > 0 else scale

    def radius(row):
        return (row.get('diameter') or spec.diameter) * scale / 2

    # Each course's radius, so a cone (or a flange) takes those of the courses beside it
    course_radii = [radius(row) if row.get('kind') == 'course' else None for row in rows]

    def neighbour(i, step):
        j = i + step
        while 0 <= j < len(rows):
            if course_radii[j] is not None:
                return course_radii[j]
            j += step
        return DRAWN_DIAMETER / 2

    segments = []
    first_radius, last_radius = neighbour(-1, 1), neighbour(len(rows), -1)
    start_bolted = spec.start_head == 'flat' and rows and rows[0].get('kind') == 'flange' and not tank
    end_bolted = spec.end_head == 'flat' and rows and rows[-1].get('kind') == 'flange' and not tank

    s = 0.0
    depth = COVER_WIDTH * 2 * first_radius if start_bolted else _head_depth(spec.start_head, 2 * first_radius, tank)
    segments.append(Segment('head', s, s + depth, first_radius, first_radius, end='start', head=spec.start_head,
                            bolted=start_bolted))
    s += depth
    tl_start = s
    inches = 0.0
    previous_radius = None
    for i, row in enumerate(rows):
        kind = row['kind']
        if kind == 'flange':
            r = neighbour(i, -1) if i > 0 else neighbour(i, 1)
            width = FLANGE_WIDTH * 2 * r
            segments.append(Segment('flange', s, s + width, r, r, inches, inches, index=i, label=row.get('label', '')))
            s += width
            continue
        length_in = row.get('length') or 0
        if kind == 'cone':
            r0, r1 = neighbour(i, -1), neighbour(i, 1)
            drawn = max(MIN_CONE, length_in * axial)
        else:
            r0 = r1 = course_radii[i]
            if previous_radius is not None and abs(previous_radius - r0) > 0.5:
                # A diameter change with no cone row between: a short cone, drawn only
                segments.append(Segment('cone', s, s + MIN_CONE, previous_radius, r0, inches, inches))
                s += MIN_CONE
            drawn = max(MIN_COURSE, length_in * axial)
        segments.append(Segment(kind, s, s + drawn, r0, r1, inches, inches + length_in, index=i,
                                label=row.get('label', '')))
        s += drawn
        inches += length_in
        previous_radius = r1
    tl_end = s
    depth = COVER_WIDTH * 2 * last_radius if end_bolted else _head_depth(spec.end_head, 2 * last_radius, tank)
    segments.append(Segment('head', s, s + depth, last_radius, last_radius, inches, inches, end='end',
                            head=spec.end_head, bolted=end_bolted))
    return Layout(segments, scale, axial, length, tl_start, tl_end)


def head_profile(seg, tank=False, steps=24):
    """The head's outline from the tangent line to the centre line, as [(s, r)] (r >= 0)."""
    import math
    r, depth = seg.r0, seg.s1 - seg.s0
    toward = -1 if seg.end == 'start' else 1          # the direction away from the shell
    tl = seg.s1 if seg.end == 'start' else seg.s0
    if seg.head == 'flat' or depth <= 0:
        return [(tl, r), (tl + toward * depth, r), (tl + toward * depth, 0.0)]
    if seg.head == 'cone':
        tip = 0.0 if tank else 0.12 * r   # a tank's cone roof comes to a point; a vessel's has a nozzle
        return [(tl, r), (tl + toward * depth, tip), (tl + toward * depth, 0.0)]
    points = []
    for k in range(steps + 1):
        t = math.pi / 2 * k / steps
        points.append((tl + toward * depth * math.sin(t), r * math.cos(t)))
    return points
