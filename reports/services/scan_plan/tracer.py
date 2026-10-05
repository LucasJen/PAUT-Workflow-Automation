"""
2D ray tracer: follows a beam through the part, reflecting it off the part's surfaces.

A beam starts at its exit point on the scanning surface and travels into the part at its
refracted angle (from the vertical, towards +x). Each surface it meets ends a leg; it reflects
there (no mode conversion) and carries on until it has run the asked number of legs or leaves
the part.
"""
import math
from dataclasses import dataclass, field

from .geometry import exit_x, part

EPSILON = 1e-9


@dataclass
class Trace:
    """A traced beam: its points (exit point, then each surface hit) and the surfaces it hit."""
    angle: float
    points: list
    surfaces: list = field(default_factory=list)

    @property
    def sound_path(self):
        """Total path length in the part, in inches."""
        return sum(math.dist(a, b) for a, b in zip(self.points, self.points[1:]))


def _hit(origin, direction, surface):
    """Distance along the ray to `surface` (a Surface), or None when the ray misses it."""
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


def _reflect(direction, surface):
    (dx, dy), (ax, ay), (bx, by) = direction, surface.a, surface.b
    length = math.hypot(bx - ax, by - ay)
    nx, ny = -(by - ay) / length, (bx - ax) / length
    dot = dx * nx + dy * ny
    return dx - 2 * dot * nx, dy - 2 * dot * ny


def trace(the_part, start, angle, legs):
    """The beam leaving `start` at `angle` degrees, followed for `legs` legs."""
    a = math.radians(angle)
    direction = (math.sin(a), math.cos(a))
    result = Trace(angle, [start])
    origin, current = start, None
    for _ in range(legs):
        hits = [(s, surface) for surface in the_part.surfaces if surface is not current
                for s in [_hit(origin, direction, surface)] if s is not None]
        if not hits:
            break
        s, current = min(hits, key=lambda hit: hit[0])
        origin = (origin[0] + direction[0] * s, origin[1] + direction[1] * s)
        result.points.append(origin)
        result.surfaces.append(current.name)
        direction = _reflect(direction, current)
    return result


def beam_path(plan, angle, x0=None):
    """(exit, back-wall bounce, top-surface return) points of one beam leaving the wedge at x0."""
    x0 = exit_x(plan) if x0 is None else x0
    return trace(part(plan), (x0, 0.0), angle, plan.legs).points
