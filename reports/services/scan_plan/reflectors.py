"""
Reflectors a scan plan checks its beams against: side-drilled holes, OD / ID notches, embedded
planar flaws and lack of sidewall fusion on a fusion face. Beams aren't stopped or echoed by them
(a coverage view, like the rest of the plan): each beam that passes through one is listed with
the leg it's on and its sound path to it, and the best beam is picked - the one passing closest
to a hole's centre, or meeting a planar reflector most nearly square-on.

A reflector is stored as {kind, label, side, distance, depth, size, angle} (lengths in inches):
side 90 / 270 is the weld side it's on (90: the -x side, where the 90 deg skew's probe sits),
distance its position from the weld centre line (along the OD round a pipe), depth below the OD,
size a hole's diameter or a notch's / flaw's height, angle a notch's / flaw's tilt from
vertical (positive leans its top towards the weld centre line). An OD notch starts at the
surface and an ID notch at the back wall, so their depth is unused; a sidewall flaw lies on the
side's fusion face centred at its depth, so its distance and angle are unused.
"""
import math
from dataclasses import dataclass

from .geometry import back_wall, od_radius, weld_faces, wrap, wrap_path

KINDS = {
    'sdh': 'Side-drilled hole',
    'od_notch': 'OD notch',
    'id_notch': 'ID notch',
    'flaw': 'Planar flaw',
    'sidewall': 'Sidewall lack of fusion',
}
SHORT = {'sdh': 'SDH', 'od_notch': 'OD notch', 'id_notch': 'ID notch', 'flaw': 'Flaw', 'sidewall': 'LOF'}
# Which values each kind uses (the editor shows only these)
USES = {
    'sdh': ('side', 'distance', 'depth', 'size'),
    'od_notch': ('side', 'distance', 'size', 'angle'),
    'id_notch': ('side', 'distance', 'size', 'angle'),
    'flaw': ('side', 'distance', 'depth', 'size', 'angle'),
    'sidewall': ('side', 'depth', 'size'),
}
CIRCLE_STEPS = 32


def clean(raw, thickness=None):
    """
    The reflector list as stored: checked, numbers as floats and every kind's unused values
    dropped. Raises ValueError with a message for the form.
    """
    if raw in (None, ''):
        return []
    if not isinstance(raw, list):
        raise ValueError('Reflectors must be a list.')
    out = []
    for n, item in enumerate(raw, 1):
        if not isinstance(item, dict) or item.get('kind') not in KINDS:
            raise ValueError(f'Reflector {n}: pick a type.')
        kind = item['kind']
        label = str(item.get('label') or '').strip()[:40] or f'{SHORT[kind]} {n}'
        clean_item = {'kind': kind, 'label': label}
        for name in USES[kind]:
            value = item.get(name)
            if name == 'side':
                clean_item['side'] = 270 if str(value) == '270' else 90
                continue
            if value in (None, ''):
                if name == 'angle':
                    value = 0.0
                else:
                    raise ValueError(f'{label}: enter its {_NAMES[name]}.')
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f'{label}: its {_NAMES[name]} must be a number.') from None
            if name in ('distance', 'depth') and value < 0:
                raise ValueError(f'{label}: its {_NAMES[name]} cannot be negative.')
            if name == 'size' and value <= 0:
                raise ValueError(f'{label}: its {_NAMES[name]} must be more than 0.')
            if name == 'angle' and not -89 <= value <= 89:
                raise ValueError(f'{label}: enter a tilt from -89 to 89°.')
            if name == 'depth' and thickness and value > thickness:
                raise ValueError(f'{label}: its depth is past the wall thickness.')
            clean_item[name] = value
        out.append(clean_item)
    return out


_NAMES = {'distance': 'distance from the weld C/L', 'depth': 'depth', 'size': 'size', 'angle': 'tilt'}


@dataclass
class Shape:
    """A reflector in the drawing's coordinates: a hole (centre, radius) or a line (path)."""
    label: str
    kind: str
    centre: tuple = None
    radius: float = None
    path: list = None


def _flat(plan, item):
    """The reflector laid out flat in the weld's own coordinates: (centre, radius) or a path."""
    kind = item['kind']
    x = item.get('distance', 0.0) * (-1 if item['side'] == 90 else 1)
    towards = 1 if x < 0 else -1 if x > 0 else 1        # towards the weld centre line
    size = item['size']
    tilt = math.radians(item.get('angle', 0.0))
    lean, drop = towards * math.sin(tilt), math.cos(tilt)
    if kind == 'sdh':
        return (x, item['depth']), size / 2, None
    if kind == 'od_notch':
        return None, None, [(x, 0.0), (x + lean * size, drop * size)]
    if kind == 'id_notch':
        base = _back_wall_at(plan, x)
        return None, None, [(x, base), (x + lean * size, base - drop * size)]
    if kind == 'flaw':
        cx, cy = x, item['depth']
        half = size / 2
        return None, None, [(cx - lean * half, cy - drop * half), (cx + lean * half, cy + drop * half)]
    # Sidewall: along the side's fusion face, centred where it reaches the depth
    left, right = weld_faces(plan)
    face = left if item['side'] == 90 else right
    return None, None, _along_face(face, item['depth'], size)


def _back_wall_at(plan, x):
    if od_radius(plan) is not None:
        return plan.thickness
    wall = back_wall(plan, x - 1e-6, x + 1e-6)
    return wall[0][1]


def _along_face(face, depth, size):
    """A piece of the fusion face `size` long, centred where it reaches `depth`."""
    depth = min(max(depth, face[0][1]), face[-1][1])
    for (ax, ay), (bx, by) in zip(face, face[1:]):
        if ay <= depth <= by and by > ay:
            t = (depth - ay) / (by - ay)
            cx, cy = ax + (bx - ax) * t, depth
            length = math.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / length, (by - ay) / length
            half = size / 2
            return [(cx - ux * half, cy - uy * half), (cx + ux * half, cy + uy * half)]
    cx, cy = face[-1]
    return [(cx, cy - size), (cx, cy)]


def shapes(plan, sign=1):
    """
    The plan's reflectors in a drawing's coordinates: laid out where they are on the weld,
    turned round for a mirrored (270 deg) drawing (`sign` -1) and wrapped onto a pipe.
    """
    out = []
    for item in plan.reflectors or []:
        centre, radius, path = _flat(plan, item)
        if centre is not None:
            cx, cy = wrap(plan, centre[0], centre[1])
            out.append(Shape(item['label'], item['kind'], centre=(sign * cx, cy), radius=radius))
        else:
            points = wrap_path(plan, path, step=0.01) if od_radius(plan) is not None else path
            out.append(Shape(item['label'], item['kind'], path=[(sign * px, py) for px, py in points]))
    return out


def circle_points(shape):
    (cx, cy), r = shape.centre, shape.radius
    return [(cx + r * math.cos(2 * math.pi * i / CIRCLE_STEPS), cy + r * math.sin(2 * math.pi * i / CIRCLE_STEPS))
            for i in range(CIRCLE_STEPS)]


def hit(points, shape):
    """
    Where a beam (its points) first meets the reflector: {leg, sound_path, point} plus `miss`
    (closest approach to a hole's centre) or `incidence` (degrees off square-on to a line); or None.
    """
    travelled = 0.0
    for leg, (a, b) in enumerate(zip(points, points[1:]), 1):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        ux, uy = dx / length, dy / length
        if shape.centre is not None:
            (cx, cy), r = shape.centre, shape.radius
            along = (cx - a[0]) * ux + (cy - a[1]) * uy
            miss = abs((cx - a[0]) * uy - (cy - a[1]) * ux)
            if miss <= r and -r <= along <= length + r:
                entry = max(along - math.sqrt(r * r - miss * miss), 0.0)
                if entry <= length:
                    return {'leg': leg, 'sound_path': travelled + entry, 'miss': miss,
                            'point': (a[0] + ux * entry, a[1] + uy * entry)}
        else:
            best = None
            for p, q in zip(shape.path, shape.path[1:]):
                crossing = _cross(a, (dx, dy), p, q)
                if crossing is not None and (best is None or crossing < best[0]):
                    best = (crossing, p, q)
            if best is not None:
                s, p, q = best
                ex, ey = q[0] - p[0], q[1] - p[1]
                e = math.hypot(ex, ey)
                square_on = abs(ux * ey / e - uy * ex / e)          # |beam . reflector normal|
                incidence = math.degrees(math.acos(min(square_on, 1.0)))
                return {'leg': leg, 'sound_path': travelled + s * length, 'incidence': incidence,
                        'point': (a[0] + dx * s, a[1] + dy * s)}
        travelled += length
    return None


def _cross(a, d, p, q):
    """Fraction (0..1) along a + t*d where it crosses segment p-q, or None."""
    ex, ey = q[0] - p[0], q[1] - p[1]
    denominator = d[0] * ey - d[1] * ex
    if abs(denominator) < 1e-12:
        return None
    t = ((p[0] - a[0]) * ey - (p[1] - a[1]) * ex) / denominator
    u = ((p[0] - a[0]) * d[1] - (p[1] - a[1]) * d[0]) / denominator
    return t if 0 <= t <= 1 and 0 <= u <= 1 else None


def summary(shape, beam_hits):
    """
    {label, kind, hits: [{angle, leg, sound_path, miss|incidence}], best} for one drawing, from
    [(angle, hit)] of the beams that met the reflector.
    """
    hits = [{'angle': angle, **{k: v for k, v in h.items() if k != 'point'}} for angle, h in beam_hits]
    if not hits:
        best = None
    elif shape.centre is not None:
        best = min(hits, key=lambda h: h['miss'])
    else:
        best = min(hits, key=lambda h: h['incidence'])
    return {'label': shape.label, 'kind': shape.kind, 'hits': hits, 'best': best}
