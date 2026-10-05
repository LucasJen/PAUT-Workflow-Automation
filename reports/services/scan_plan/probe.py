"""
Where the wedge, probe and beam exit points go: from the catalogue's probe and wedge (or the
wedge geometry a setup's .nde recorded), else a sketched wedge at the entered exit point.
"""
import copy
import math
from dataclasses import dataclass, field
from types import SimpleNamespace

from .geometry import (
    GENERIC_PROBE, GENERIC_WEDGE, M_PER_S_TO_IN_PER_US, MM_PER_IN, REXOLITE_VELOCITY, angles, exit_x,
    index_offset, part_velocity, related,
)

HEEL_FRACTION = 0.15                  # estimated probe face height at the wedge heel, of the wedge height
PROBE_BLOCK_THICKNESS = 2.0 / 25.4    # drawn probe element block thickness, in (like OmniScan's)
BLOCK_MARGIN = 1.0 / 25.4             # drawn probe block beyond the end elements, in

# Sketched wedge (no probe or wedge picked): only the front face position and the exit point are real
WEDGE_LENGTH = 1.5
WEDGE_HEEL = 0.15
PROBE_LENGTH = 0.7
PROBE_HEIGHT = 0.28
WEDGE_PATH = 0.45                     # beam path in the wedge, probe face to exit point

@dataclass
class Layout:
    """Where the wedge, probe and beams go. `exits` maps each beam angle to its exit point x."""
    wedge: list
    probe: list
    face: tuple                 # probe face end points
    source: tuple               # where the beams in the wedge start
    exits: dict
    aperture: tuple = None      # active aperture on the probe face (catalogue layout only)
    exact: bool = False
    estimated: list = field(default_factory=list)   # catalogue values that had to be estimated
    from_file: bool = False     # wedge geometry from the .nde of the setup the plan was filled from
    wedge_data: dict = None     # the wedge numbers the layout used (mm, degrees, m/s), for the page
    ratio: float = None         # wedge velocity / part velocity: sin(incidence) = ratio * sin(refracted)


def _known(value, default, name, estimated):
    """`value`, or `default` noted in `estimated` under `name` when the catalogue doesn't have it."""
    if value is None:
        estimated.append(name)
        return default
    return value


def catalogue_layout(plan):
    """
    Wedge, probe and beam exit points from the catalogue's probe and wedge, or None when neither is
    picked. Values the catalogue entries don't have yet are estimated and listed in
    Layout.estimated; with none estimated the layout is exact.

    The active aperture's centre sits on the probe face, `pitch` per element up the slope from the
    first element (whose position the wedge's primary offset and first element height give). Each
    beam leaves that point at the incident angle Snell's law gives for its refracted angle.
    """
    probe, wedge = related(plan, 'probe_model'), related(plan, 'wedge_model')
    if probe is None and wedge is None:
        return None
    estimated = []
    probe_values = probe if probe is not None else GENERIC_PROBE
    wedge_values = wedge if wedge is not None else GENERIC_WEDGE
    if probe is None:
        estimated.append('probe (none picked)')
    if wedge is None:
        estimated.append('wedge (none picked)')

    # Wedge geometry recorded in a setup's .nde file (offsets, angle, velocity and its size)
    # replaces the catalogue's: the file is what the instrument used
    file_offset = getattr(plan, 'wedge_primary_offset', None)
    from_file = file_offset is not None
    if from_file:
        wedge_values = SimpleNamespace(
            length=getattr(plan, 'wedge_length', None) or wedge_values.length,
            height=getattr(plan, 'wedge_height', None) or wedge_values.height,
            refracted_angle=wedge_values.refracted_angle,
            wave_type=getattr(wedge_values, 'wave_type', 'SW'), wedge_angle=plan.wedge_angle,
            velocity=getattr(plan, 'wedge_velocity', None) or wedge_values.velocity, primary_offset=file_offset,
            first_element_height=getattr(plan, 'wedge_first_element_height', None))

    pitch = _known(probe_values.pitch, GENERIC_PROBE.pitch, 'pitch', estimated) / MM_PER_IN
    total = probe_values.elements or GENERIC_PROBE.elements
    housing = _known(probe_values.length, total * pitch * MM_PER_IN + 4, 'probe length', estimated) / MM_PER_IN
    length = _known(wedge_values.length, GENERIC_WEDGE.length, 'wedge length', estimated) / MM_PER_IN
    height = _known(wedge_values.height, GENERIC_WEDGE.height, 'wedge height', estimated) / MM_PER_IN
    velocity = _known(wedge_values.velocity, REXOLITE_VELOCITY, 'wedge velocity', estimated)
    ratio = (velocity * M_PER_S_TO_IN_PER_US) / part_velocity(plan, wedge)

    wedge_angle = wedge_values.wedge_angle
    if wedge_angle is None:
        # Probe face angle that refracts the wedge's nominal angle
        refracted = wedge_values.refracted_angle
        sin_i = ratio * math.sin(math.radians(refracted)) if refracted is not None else None
        wedge_angle = math.degrees(math.asin(sin_i)) if sin_i is not None and sin_i < 1 else plan.wedge_angle
        estimated.append('wedge angle')
    a = math.radians(wedge_angle)
    cos_a, sin_a = math.cos(a), math.sin(a)
    first = min(max(plan.first_element or 1, 1), total)
    count = min(plan.aperture_elements or total, total - first + 1)
    front = -index_offset(plan)
    back = front - length

    # First element: from the wedge's offsets, else the housing sits at the wedge's heel
    margin = max((housing - total * pitch) / 2, 0) + pitch / 2   # housing end to first element centre
    h1 = wedge_values.first_element_height
    offset = wedge_values.primary_offset
    if h1 is not None and offset is not None:
        h1, x1 = h1 / MM_PER_IN, front + offset / MM_PER_IN
    else:
        # The probe face starts a little above the wedge heel (about 15% of the wedge height, as
        # OmniScan draws the SA wedges); the first element sits on it at its catalogue height, or
        # with the housing starting at the heel when that height isn't known either.
        estimated.append('first element position')
        heel = height * 0.6 if sin_a < 1e-6 else height * HEEL_FRACTION
        h1 = h1 / MM_PER_IN if h1 is not None else heel + margin * sin_a
        h1 = min(max(h1, heel), height)
        x1 = back + (h1 - heel) / sin_a * cos_a if sin_a > 1e-6 else back + margin

    def face(s):
        """Point on the probe face, s inches up the slope from the first element's centre."""
        return (x1 + s * cos_a, -(h1 + s * sin_a))

    s_first, s_last = (first - 1) * pitch, (first + count - 2) * pitch
    cx, cy = face((s_first + s_last) / 2)
    exits = {}
    for angle in angles(plan):
        sin_i = ratio * math.sin(math.radians(angle))
        if sin_i < 1:  # beyond the critical angle there is no refracted beam
            exits[angle] = cx - cy * math.tan(math.asin(sin_i))

    # Wedge outline at its catalogue size, the face passing through the first element
    outline = [(front, 0.0)]
    if sin_a > 1e-6:
        def h_at(x):
            return h1 + (x - x1) * sin_a / cos_a
        x_top = x1 + (height - h1) * cos_a / sin_a
        if x_top < front:
            outline += [(front, -height), (x_top, -height)]
        else:
            outline.append((front, -h_at(front)))
        if h_at(back) > 0:
            outline += [(back, -h_at(back)), (back, 0.0)]
        else:
            outline.append((x1 - h1 * cos_a / sin_a, 0.0))
    else:  # flat (0°) wedge: the probe sits in a pocket
        outline += [(front, -height), (back, -height), (back, 0.0)]

    # Probe: a thin element block (the array plus a small margin) lying on the face, as OmniScan
    # draws it; drawn whole even where it passes the wedge's back
    block = total * pitch + 2 * BLOCK_MARGIN
    stand = PROBE_BLOCK_THICKNESS
    array_mid = (total - 1) / 2 * pitch
    nx, ny = -sin_a, -cos_a
    p1, p2 = face(array_mid - block / 2), face(array_mid + block / 2)
    probe_outline = [p1, p2, (p2[0] + nx * stand, p2[1] + ny * stand), (p1[0] + nx * stand, p1[1] + ny * stand)]

    heel = max(h1 - (x1 - back) * sin_a / cos_a, 0.0) if sin_a > 1e-6 else height
    if from_file:
        source = '.nde file'
    elif estimated:
        source = 'catalogue, estimated: ' + ', '.join(estimated)
    else:
        source = 'catalogue'
    wedge_data = {
        'source': source,
        'length': length * MM_PER_IN, 'height': height * MM_PER_IN, 'angle': wedge_angle,
        'velocity': velocity,
        'first_element_behind_front': (front - x1) * MM_PER_IN, 'first_element_height': h1 * MM_PER_IN,
        'heel_height': heel * MM_PER_IN,
    }
    return Layout(outline, probe_outline, (p1, p2), (cx, cy), exits,
                  aperture=(face(s_first - pitch / 2), face(s_last + pitch / 2)),
                  exact=not estimated, estimated=estimated, from_file=from_file, wedge_data=wedge_data,
                  ratio=ratio)


def exact_layout(plan):
    """The catalogue layout when nothing in it had to be estimated, else None."""
    lay = catalogue_layout(plan)
    return lay if lay is not None and lay.exact else None


def layout(plan):
    """The catalogue layout when a probe or wedge is picked, else the sketched wedge."""
    lay = catalogue_layout(plan)
    if lay is not None:
        return lay
    wedge, probe, centre, face = _wedge(plan)
    x0 = exit_x(plan)
    ratio = REXOLITE_VELOCITY * M_PER_S_TO_IN_PER_US / part_velocity(plan, None)
    return Layout(wedge, probe, face, (x0, 0.0), {angle: x0 for angle in angles(plan)}, ratio=ratio)


def _wedge(plan):
    """Sketched wedge: (wedge polygon, probe polygon, probe face centre, probe face end points)."""
    a = math.radians(plan.wedge_angle)
    x0 = exit_x(plan)
    front = -index_offset(plan)
    # Probe face centre: up and back from the exit point along the central ray
    cx, cy = x0 - WEDGE_PATH * math.sin(a), -WEDGE_PATH * math.cos(a)
    along = (math.cos(a), -math.sin(a))        # up the slope, towards the front
    normal = (-math.sin(a), -math.cos(a))      # out of the wedge, away from the exit point

    def on_slope(y):
        return cx + (y - cy) / along[1] * along[0]

    top = cy - PROBE_LENGTH / 2 * math.sin(a) - 0.12
    back = on_slope(-WEDGE_HEEL)
    back = min(back, front - WEDGE_LENGTH * 0.6)
    slope_top_x = min(on_slope(top), front - 0.1)
    wedge = [(back, 0.0), (front, 0.0), (front, top), (slope_top_x, top), (back, -WEDGE_HEEL)]

    h = PROBE_LENGTH / 2
    p1 = (cx - along[0] * h, cy - along[1] * h)
    p2 = (cx + along[0] * h, cy + along[1] * h)
    probe = [p1, p2,
             (p2[0] + normal[0] * PROBE_HEIGHT, p2[1] + normal[1] * PROBE_HEIGHT),
             (p1[0] + normal[0] * PROBE_HEIGHT, p1[1] + normal[1] * PROBE_HEIGHT)]
    return wedge, probe, (cx, cy), (p1, p2)


def at_position(plan, position):
    """The plan with its second index offset as the index offset (position 2), else the plan."""
    if position != 2:
        return plan
    second = copy.copy(plan)
    second.index_offset = plan.index_offset_2
    return second
