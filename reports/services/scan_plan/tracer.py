"""
2D ray tracer: follows a beam through the part, reflecting it off the part's surfaces.

A beam starts at its exit point on the scanning surface and travels into the part at its
refracted angle (from the vertical, towards +x), or along a given direction. Each surface it
meets (a straight Surface or a Circle: a pipe's OD / ID) ends a leg; it reflects there (no mode
conversion) and carries on until it has run the asked number of legs or leaves the part.
"""
import math
from dataclasses import dataclass, field

from .geometry import Circle, exit_x, part

EPSILON = 1e-9
CIRCLE_EPSILON = 1e-7     # a circle hit this close to the ray's start is the start itself


@dataclass
class Trace:
    """A traced beam: its points (exit point, then each surface hit) and the surfaces it hit."""
    angle: float
    points: list
    surfaces: list = field(default_factory=list)
    refracted: float = None     # the angle it actually enters at, from the surface normal (curved parts)

    @property
    def sound_path(self):
        """Total path length in the part, in inches."""
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))


def _hit(origin, direction, surface):
    """Distance along the ray to `surface` (a Surface or Circle), or None when the ray misses it."""
    if isinstance(surface, Circle):
        return circle_hit(origin, direction, surface)
    (ox, oy), (dx, dy) = origin, direction
    (ax, ay), (bx, by) = surface.a, surface.b
    ex, ey = bx - ax, by - ay
    denominator = dx * ey - dy * ex
    if abs(denominator) < EPSILON:  # parallel
        return None
    s = ((ax - ox) * ey - (ay - oy) * ex) / denominator     # along the ray
    u = ((ax - ox) * dy - (ay - oy) * dx) / denominator     # along the surface, 0..1
    if s <= EPSILON or u < -EPSILON or u > 1 + EPSILON:
        return None
    return s


def circle_hit(origin, direction, circle, nearest_from=CIRCLE_EPSILON):
    """Distance along the ray (unit direction) to the circle, beyond `nearest_from`, or None."""
    (ox, oy), (dx, dy), (cx, cy) = origin, direction, circle.centre
    fx, fy = ox - cx, oy - cy
    b = fx * dx + fy * dy
    c = fx * fx + fy * fy - circle.radius ** 2
    disc = b * b - c
    if disc < 0:
        return None
    root = math.sqrt(disc)
    for s in (-b - root, -b + root):
        if s > nearest_from:
            return s
    return None


def _reflect(direction, surface, point):
    if isinstance(surface, Circle):
        (px, py), (cx, cy) = point, surface.centre
        length = math.hypot(px - cx, py - cy)
        return reflect(direction, ((px - cx) / length, (py - cy) / length))
    (dx, dy), (ax, ay), (bx, by) = direction, surface.a, surface.b
    length = math.hypot(bx - ax, by - ay)
    nx, ny = -(by - ay) / length, (bx - ax) / length
    dot = dx * nx + dy * ny
    return dx - 2 * dot * nx, dy - 2 * dot * ny


def reflect(direction, normal):
    """`direction` mirrored off a surface with this unit normal (either sign)."""
    (dx, dy), (nx, ny) = direction, normal
    dot = dx * nx + dy * ny
    return dx - 2 * dot * nx, dy - 2 * dot * ny


def trace(the_part, start, angle, legs, direction=None, refracted=None):
    """
    The beam leaving `start` at `angle` degrees (or along the unit `direction`, for a curved part
    where the beam bends at the surface), followed for `legs` legs.
    """
    if direction is None:
        a = math.radians(angle)
        direction = (math.sin(a), math.cos(a))
    result = Trace(angle, [start], refracted=refracted)
    origin, current = start, None
    for _ in range(legs):
        # A straight surface just hit can't be hit again straight away; a circle can (the far side)
        hits = [(s, surface) for surface in the_part.surfaces
                if surface is not current or isinstance(surface, Circle)
                for s in [_hit(origin, direction, surface)] if s is not None]
        if not hits:
            break
        s, current = min(hits, key=lambda hit: hit[0])
        origin = (origin[0] + direction[0] * s, origin[1] + direction[1] * s)
        result.points.append(origin)
        result.surfaces.append(current.name)
        direction = _reflect(direction, current, origin)
    return result


def beam_path(plan, angle, x0=None):
    """(exit, back-wall bounce, top-surface return) points of one beam leaving the wedge at x0."""
    x0 = exit_x(plan) if x0 is None else x0
    return trace(part(plan), (x0, 0.0), angle, plan.legs).points
