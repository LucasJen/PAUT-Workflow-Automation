"""
A scan plan's fan: where the wedge and probe sit, the rays in the wedge and each beam's path
through the part.

Flat section (axial beams): each beam leaves the wedge's flat bottom at its exit point
(Layout.exits) at its refracted angle.

Curved section (circumferential beams round a pipe): the wedge sits on the OD - a contoured
wedge's bottom follows the OD; a flat wedge touches it under the middle of its bottom and lifts
off towards its ends. Each beam leaves the probe at the incidence the focal law gives for a flat
part (sin i = ratio * sin(nominal angle)), so it meets the curved OD at a different angle and
refracts by Snell's law at the local surface normal: its refracted angle in the part drifts from
the nominal one. The couplant under a flat wedge's ends is traced as wedge material and its
thickness reported as the lift-off.
"""
import math
from dataclasses import dataclass, field

from .geometry import index_offset, od_radius, part
from .probe import layout
from .tracer import circle_hit, trace

CONTOUR_STEPS = 24     # straight pieces drawing a contoured wedge's bottom
LIFT_OFF_WARNING = 0.5 / 25.4   # in: a flat wedge's gap above this is flagged (procedures set their own limit)


@dataclass
class Fan:
    wedge: list                 # wedge outline
    probe: list                 # probe (element block) outline
    aperture: tuple             # the active aperture's ends on the probe face, or None (sketched wedge)
    wedge_rays: list            # [(a, b)] rays drawn in the wedge
    traces: list                # tracer.Trace per beam, in angle order
    front: tuple                # the wedge front's bottom corner
    lift_off: float = None      # a flat wedge's gap to the OD at its farther end (curved section), in
    couplant: list = field(default_factory=list)   # that gap as a polygon, to shade


def fan(plan):
    """The plan's wedge, probe and beams (at its index offset)."""
    lay = layout(plan)
    if od_radius(plan) is not None:
        return _curved_fan(plan, lay)
    the_part = part(plan)
    traces = [trace(the_part, (x0, 0.0), angle, plan.legs) for angle, x0 in lay.exits.items()]
    return Fan(lay.wedge, lay.probe, lay.aperture, _wedge_rays(lay), traces, (-index_offset(plan), 0.0))


def _wedge_rays(lay, place=lambda p: p):
    """Rays in the wedge: from the active aperture to each exit point, or a sketched fan to the exit point."""
    if lay.aperture:
        return [(place(lay.source), place((x0, 0.0))) for x0 in lay.exits.values()]
    (p1, p2) = lay.face
    return [(place((p1[0] + (p2[0] - p1[0]) * i / 8, p1[1] + (p2[1] - p1[1]) * i / 8)), place(lay.source))
            for i in range(9)]


def _curved_fan(plan, lay):
    radius = od_radius(plan)
    centre = (0.0, radius)
    the_part = part(plan)
    od = the_part.surfaces[0]
    contoured = getattr(plan, 'wedge_contour', 'flat') == 'contoured'

    # The wedge's bottom runs from its back (or where its slope meets the bottom) to its front
    bottom = [p for p in lay.wedge if abs(p[1]) < 1e-12]
    back, front = min(p[0] for p in bottom), max(p[0] for p in bottom)
    middle = (back + front) / 2

    # Where the bottom's middle touches the OD: the wedge front's radial projection on the OD is
    # the index offset (along the OD) from the weld centre line
    half = front - middle
    if contoured:   # the front corner is on the OD: asin(half / radius) round from where the middle touches
        theta = front / radius - math.asin(min(half / radius, 1.0))
    else:           # the front corner is above the OD: its radial projection is atan(half / radius) round
        theta = front / radius - math.atan(half / radius)
    touch = (radius * math.sin(theta), radius - radius * math.cos(theta))
    along, down = (math.cos(theta), math.sin(theta)), (-math.sin(theta), math.cos(theta))

    def place(point):
        """A point of the flat layout (x, y below the bottom) on the wedge sitting on the pipe."""
        u, v = point[0] - middle, point[1]
        return (touch[0] + u * along[0] + v * down[0], touch[1] + u * along[1] + v * down[1])

    def sag(x):
        """How far the OD falls below the wedge's bottom line at x."""
        u = x - middle
        return radius - math.sqrt(max(radius * radius - u * u, 0.0))

    # Start the outline at the front's bottom corner, so its closing edge is the bottom
    start = next(i for i, p in enumerate(lay.wedge) if abs(p[1]) < 1e-12 and p[0] == front)
    outline = lay.wedge[start:] + lay.wedge[:start]
    if contoured:   # the bottom follows the OD: the closing edge from the last point to the front
        outline[0] = (outline[0][0], sag(outline[0][0]))
        last_x = outline[-1][0]
        outline[-1] = (last_x, sag(last_x))
        outline += [(x, sag(x)) for x in (last_x + (front - last_x) * i / CONTOUR_STEPS for i in range(1, CONTOUR_STEPS))]
    wedge = [place(p) for p in outline]

    ratio, speed_up = lay.ratio, 1 / lay.ratio
    traces, rays = [], []
    for angle, x0 in lay.exits.items():
        sin_i = ratio * math.sin(math.radians(angle))
        if sin_i >= 1:
            continue
        cos_i = math.sqrt(1 - sin_i * sin_i)
        d = (sin_i * along[0] + cos_i * down[0], sin_i * along[1] + cos_i * down[1])
        start = place((x0, 0.0))
        s = circle_hit(start, d, od, nearest_from=-1e-9)
        if s is None:
            continue
        entry = (start[0] + d[0] * s, start[1] + d[1] * s)
        # Snell's law at the OD's normal there (pointing into the wall, towards the pipe's centre)
        nx, ny = centre[0] - entry[0], centre[1] - entry[1]
        length = math.hypot(nx, ny)
        nx, ny = nx / length, ny / length
        dot = d[0] * nx + d[1] * ny
        tx, ty = speed_up * (d[0] - dot * nx), speed_up * (d[1] - dot * ny)
        sin_r = math.hypot(tx, ty)
        if sin_r >= 1:   # beyond the critical angle on this part of the OD
            continue
        cos_r = math.sqrt(1 - sin_r * sin_r)
        direction = (tx + cos_r * nx, ty + cos_r * ny)
        traces.append(trace(the_part, entry, angle, plan.legs, direction=direction,
                            refracted=math.degrees(math.asin(sin_r))))
        rays.append((place(lay.source) if lay.aperture else start, entry))
    if not lay.aperture:
        rays = _wedge_rays(lay, place) + rays

    if contoured:
        lift_off, couplant = 0.0, []
    else:
        lift_off = max(sag(back), sag(front))
        line = [place((back + (front - back) * i / CONTOUR_STEPS, 0.0)) for i in range(CONTOUR_STEPS + 1)]
        on_od = []
        for x, y in line:   # each point's radial projection onto the OD
            dx, dy = x - centre[0], y - centre[1]
            scale = radius / math.hypot(dx, dy)
            on_od.append((centre[0] + dx * scale, centre[1] + dy * scale))
        couplant = line + on_od[::-1]

    front_corner = place((front, sag(front) if contoured else 0.0))
    aperture = tuple(place(p) for p in lay.aperture) if lay.aperture else None
    return Fan(wedge, [place(p) for p in lay.probe], aperture, rays, traces, front_corner, lift_off, couplant)
