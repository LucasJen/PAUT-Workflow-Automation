"""
The part and weld of a scan plan: units, beam angles, the single-V weld outline, the index offset
and the part's surfaces for the tracer.

All geometry is in inches with the weld centre line at x = 0, the scanning surface at y = 0
and depth increasing downwards. The probe sits on the -x side; side 2 is the mirror image.

Circumferential beams (across a long seam) travel round the pipe: the section is an annulus
with its centre at (0, OD radius), so the OD's top is still (0, 0). The weld, HAZ and cap are
laid out flat first (x along the OD, y the depth below it) and wrapped onto the pipe (wrap()).
"""
import math
import re
from dataclasses import dataclass
from types import SimpleNamespace

from django.core.exceptions import ObjectDoesNotExist

MM_PER_IN = 25.4
M_PER_S_TO_IN_PER_US = 1 / 25400
STEEL_SHEAR = 0.1276                  # in/µs
STEEL_LONGITUDINAL = 0.2320
REXOLITE_VELOCITY = 2330.0            # m/s, typical wedge material when the catalogue has none

# Stand-ins when only one of probe / wedge is picked (mm): an A1 probe on an SA1 wedge
GENERIC_PROBE = SimpleNamespace(pitch=0.6, elements=16, length=17.0, height=25.0)
GENERIC_WEDGE = SimpleNamespace(length=30.0, height=16.0, velocity=None, wedge_angle=None, refracted_angle=None,
                                first_element_height=None, primary_offset=None, wave_type='SW')

PLATE_EXTENT = 1000.0                 # a flat plate's surfaces run this far each way, in


def fmt_in(value):
    return f'{value:.3f}"'


def fmt_length(plan, inches):
    """A length for the drawing in the plan's units."""
    if getattr(plan, 'units', 'imperial') == 'metric':
        return f'{inches * MM_PER_IN:.2f} mm'
    return fmt_in(inches)


def first_number(text):
    match = re.search(r'-?\d+(?:\.\d+)?', text or '')
    return float(match.group()) if match else None


def related(plan, name):
    """A plan's probe_model / wedge_model, or None (also for unsaved plans built from a form)."""
    try:
        return getattr(plan, name, None)
    except ObjectDoesNotExist:
        return None


def part_velocity(plan, wedge):
    """Part velocity in in/µs for the wedge's wave type (L-wave wedges refract a longitudinal beam)."""
    if wedge is not None and wedge.wave_type == 'LW':
        block = related(plan, 'sensitivity_block')
        return first_number(block.velocity_long if block else '') or STEEL_LONGITUDINAL
    return plan.shear_velocity or STEEL_SHEAR


def angles(plan):
    """Beam angles from start to stop (inclusive) in steps of angle_step."""
    start, stop = sorted((plan.angle_start, plan.angle_stop))
    step = max(plan.angle_step or 1.0, 0.1)
    count = int(math.floor((stop - start) / step + 1e-9))
    return [start + i * step for i in range(count + 1)] + ([stop] if (stop - start) % step > 1e-6 else [])


ARC_STEPS = 12                        # straight pieces drawing a J / U groove's root radius


def _tan(degrees):
    return math.tan(math.radians(degrees))


def od_radius(plan):
    """
    The pipe's OD radius when the beams travel round it (circumferential), else None: the section
    is flat. The OD is the plan's, else its sensitivity block's test diameter.
    """
    if getattr(plan, 'beam_direction', None) != 'circumferential':
        return None
    od = getattr(plan, 'outside_diameter', None)
    if not od:
        block = related(plan, 'sensitivity_block')
        od = first_number(block.test_diameter or block.cal_diameter) if block else None
    return od / 2 if od and od / 2 > plan.thickness else None


def outside_diameter(plan):
    """The OD a circumferential plan is drawn with (inches), else None."""
    radius = od_radius(plan)
    return radius * 2 if radius else None


def wrap(plan, x, depth):
    """A point laid out flat (x along the OD from the weld centre line, depth below it) on the pipe."""
    radius = od_radius(plan)
    if radius is None:
        return (x, depth)
    theta, r = x / radius, radius - depth
    return (r * math.sin(theta), radius - r * math.cos(theta))


def wrap_path(plan, points, step=0.02):
    """A flat polyline on the pipe, its straight pieces split every `step` inches so they bend round it."""
    if od_radius(plan) is None:
        return points
    out = []
    for a, b in zip(points, points[1:]):
        pieces = max(1, math.ceil(math.dist(a, b) / step))
        out += [wrap(plan, a[0] + (b[0] - a[0]) * i / pieces, a[1] + (b[1] - a[1]) * i / pieces) for i in range(pieces)]
    return out + [wrap(plan, *points[-1])] if points else out


def arc_position(plan, point):
    """(Distance along the OD from the weld centre line, depth below the OD) of a point on the pipe."""
    radius = od_radius(plan)
    if radius is None:
        return point
    x, y = point
    return radius * math.atan2(x, radius - y), radius - math.hypot(x, y - radius)


def weld_thickness(plan):
    """Wall at the weld: the thickness less any counterbore (girth welds only)."""
    depth = (getattr(plan, 'counterbore_depth', None) or 0) if od_radius(plan) is None else 0
    return max(plan.thickness - depth, 1e-3)


def _bevel_face(plan):
    """
    The prepped fusion face on the -x side, from the cap (y = 0) down to the root, for the plan's
    weld type: a single V's bevel, a double V's two bevels, a compound bevel's two angles or a
    J / U groove's root radius and side wall.
    """
    t = weld_thickness(plan)
    half_gap = (plan.root_gap or 0) / 2
    land = min(plan.root_face or 0, t)
    kind = getattr(plan, 'weld_type', None) or 'single_v'

    if kind == 'double_v':
        top_depth = plan.land_depth if plan.land_depth is not None else (t - land) / 2
        top_depth = min(max(top_depth, 0.0), t - land)
        top = half_gap + top_depth * _tan(plan.bevel_angle)
        bottom = half_gap + (t - top_depth - land) * _tan(plan.bottom_bevel_angle)
        return _distinct([(-top, 0.0), (-half_gap, top_depth), (-half_gap, top_depth + land), (-bottom, t)])

    if kind == 'compound':
        height = min(max(plan.transition_height or 0, 0.0), t - land)
        change_y = t - land - height
        change_x = half_gap + height * _tan(plan.bevel_angle)
        top = change_x + change_y * _tan(plan.upper_bevel_angle)
        return _distinct([(-top, 0.0), (-change_x, change_y), (-half_gap, t - land), (-half_gap, t)])

    if kind in ('j_bevel', 'u_groove'):
        # The root radius starts level at the top of the land and turns up into the side wall
        # (bevel_angle from vertical): its centre is straight above the land's top edge
        radius = max(plan.root_radius or 0, 0.0)
        centre_y = t - land - radius
        end = math.radians(90 - plan.bevel_angle)
        arc = []
        for i in range(ARC_STEPS + 1):
            phi = end * i / ARC_STEPS
            x, y = -half_gap - radius * math.sin(phi), centre_y + radius * math.cos(phi)
            if y < 0:   # the radius reaches the cap: no straight side wall
                break
            arc.append((x, y))
        if not arc:
            arc = [(-half_gap, t - land)]
        end_x, end_y = arc[-1]
        top = [(end_x - end_y * _tan(plan.bevel_angle), 0.0)] if end_y > 0 else []
        return _distinct(top + arc[::-1] + [(-half_gap, t)])

    # Single V (and the prepped side of a single bevel)
    half_cap_prep = half_gap + (t - land) * _tan(plan.bevel_angle)
    return [(-half_cap_prep, 0.0), (-half_gap, t - land), (-half_gap, t)]


def _distinct(points):
    """`points` without repeats (from a zero-height land or transition)."""
    out = []
    for point in points:
        if not out or math.dist(out[-1], point) > 1e-9:
            out.append(point)
    return out


def mirror(points):
    return [(-x, y) for x, y in points]


def weld_faces(plan):
    """
    (left, right): the fusion faces on the -x and +x sides of the weld centre line, each from the
    cap down to the root. A single bevel / J bevel has its prep on `bevel_side` (90: the -x side,
    where the 90 deg skew's probe sits) and a square face on the other.
    """
    face = _bevel_face(plan)
    if getattr(plan, 'weld_type', None) in ('single_bevel', 'j_bevel'):
        half_gap = (plan.root_gap or 0) / 2
        square = [(-half_gap, 0.0), (-half_gap, weld_thickness(plan))]
        if plan.bevel_side == 90:
            return face, mirror(square)
        return square, mirror(face)
    return face, mirror(face)


def symmetric(plan):
    """Whether the weld is the same on both sides of its centre line."""
    left, right = weld_faces(plan)
    return left == mirror(right)


def weld_outline(plan):
    """The -x side's fusion face, from the cap edge down to the root."""
    return weld_faces(plan)[0]


def cap_width(plan):
    """Cap width as entered, or the groove's opening plus 1/16" overlap on each side."""
    if plan.cap_width:
        return plan.cap_width
    left, right = weld_faces(plan)
    return right[0][0] - left[0][0] + 0.125


def cap_edges(plan):
    """(left, right) x of the cap's edges: the cap is centred on the groove's opening."""
    left, right = weld_faces(plan)
    centre = (left[0][0] + right[0][0]) / 2
    half = cap_width(plan) / 2
    return centre - half, centre + half


def toe(plan):
    """Weld centre line to the farther weld toe: a wedge front this far out clears the cap either side."""
    left, right = cap_edges(plan)
    return max(-left, right)


def index_offset(plan):
    """Wedge front to the weld centre line: as entered, else the weld toe (half the cap width)."""
    return plan.index_offset if plan.index_offset is not None else toe(plan)


def exit_x(plan):
    """Beam exit (index) point: behind the wedge front by the exit point distance."""
    return -(index_offset(plan) + plan.exit_point)


@dataclass
class Surface:
    """A straight piece of the part's boundary that beams reflect off."""
    a: tuple
    b: tuple
    name: str


@dataclass
class Circle:
    """A pipe's OD or ID in the curved section circumferential beams travel in."""
    centre: tuple
    radius: float
    name: str


@dataclass
class Part:
    """The part's cross-section as the boundary surfaces the tracer reflects beams off."""
    surfaces: list
    thickness: float


def back_wall(plan, x_min=-PLATE_EXTENT, x_max=PLATE_EXTENT):
    """
    The back wall (ID) from x_min to x_max, left to right, as points: flat at the thickness, or
    with the counterbore (the weld's wall within `counterbore_length` of the centre line) and its
    tapers back to the full wall.
    """
    t = plan.thickness
    if not getattr(plan, 'counterbore_depth', None) or od_radius(plan) is not None:
        return [(x_min, t), (x_max, t)]
    bore, length = weld_thickness(plan), plan.counterbore_length
    taper = min(max(plan.counterbore_taper or 90.0, 1.0), 90.0)
    run = (t - bore) / _tan(taper) if taper < 90 else 0.0
    profile = [(-PLATE_EXTENT, t), (-length - run, t), (-length, bore), (length, bore), (length + run, t),
               (PLATE_EXTENT, t)]
    return _clip(profile, x_min, x_max)


def _clip(points, x_min, x_max):
    """The piece of a left-to-right polyline between x_min and x_max."""
    def y_at(x):
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            if ax <= x <= bx:
                return ay if bx == ax else ay + (by - ay) * (x - ax) / (bx - ax)
        return points[-1][1]
    inside = [p for p in points if x_min < p[0] < x_max]
    return [(x_min, y_at(x_min))] + inside + [(x_max, y_at(x_max))]


def part(plan):
    """
    The part as surfaces: the scanning surface (OD) and the back wall (ID), with any counterbore
    and its tapers as surfaces of their own.
    """
    t = plan.thickness
    radius = od_radius(plan)
    if radius is not None:   # round the pipe: the OD and ID circles
        return Part([Circle((0.0, radius), radius, 'scanning surface'),
                     Circle((0.0, radius), radius - t, 'back wall')], t)
    surfaces = [Surface((-PLATE_EXTENT, 0.0), (PLATE_EXTENT, 0.0), 'scanning surface')]
    wall = back_wall(plan)
    for a, b in zip(wall, wall[1:]):
        flat = a[1] == t and b[1] == t
        surfaces.append(Surface(a, b, 'back wall' if flat else 'counterbore'))
    return Part(surfaces, t)
