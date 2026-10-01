"""
Scan plan drawing for a basic single-V butt weld: plate, weld bevel and beads, wedge and probe
at the index offset, and the sectorial beam fan (first leg and the skip off the back wall).

All geometry is in inches with the weld centre line at x = 0, the scanning surface at y = 0
and depth increasing downwards. The probe sits on the -x side; side 2 is the mirror image.
render_png(plan, side) returns PNG bytes for the scan plan page and the Excel report.
"""
import io
import math
import os
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from django.core.exceptions import ObjectDoesNotExist
from PIL import Image, ImageDraw, ImageFont

MM_PER_IN = 25.4
M_PER_S_TO_IN_PER_US = 1 / 25400
STEEL_SHEAR = 0.1276                  # in/µs
STEEL_LONGITUDINAL = 0.2320
REXOLITE_VELOCITY = 2330.0            # m/s, typical wedge material when the catalogue has none
HEEL_FRACTION = 0.15                  # estimated probe face height at the wedge heel, of the wedge height
PROBE_BLOCK_THICKNESS = 2.0 / 25.4    # drawn probe element block thickness, in (like OmniScan's)
BLOCK_MARGIN = 1.0 / 25.4             # drawn probe block beyond the end elements, in

# Stand-ins when only one of probe / wedge is picked (mm): an A1 probe on an SA1 wedge
GENERIC_PROBE = SimpleNamespace(pitch=0.6, elements=16, length=17.0, height=25.0)
GENERIC_WEDGE = SimpleNamespace(length=30.0, height=16.0, velocity=None, wedge_angle=None, refracted_angle=None,
                                first_element_height=None, primary_offset=None, wave_type='SW')

WIDTH_PX = 1100
SUPERSAMPLE = 3                       # drawn large, then scaled down for smooth lines

# Wedge outline is a schematic; only the front face position and the exit point are real
WEDGE_LENGTH = 1.5
WEDGE_HEEL = 0.15
PROBE_LENGTH = 0.7
PROBE_HEIGHT = 0.28
WEDGE_PATH = 0.45                     # beam path in the wedge, probe face to exit point

PLATE = (90, 90, 90)
PLATE_FILL = (250, 250, 250)
WELD = (205, 205, 205)
WELD_LINE = (150, 150, 150)
WEDGE_FILL = (226, 228, 248)
WEDGE_LINE = (60, 60, 80)
PROBE_FILL = (238, 240, 252)
BEAM = (20, 40, 230)
WEDGE_BEAM = (120, 140, 240)
DIMENSION = (0, 120, 0)
TEXT = (40, 40, 40)
CENTRE_LINE = (120, 120, 120)


def _font(size):
    for name in ('arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf'):
        for folder in ('', os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')):
            try:
                return ImageFont.truetype(os.path.join(folder, name) if folder else name, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def fmt_in(value):
    return f'{value:.3f}"'


def fmt_length(plan, inches):
    """A length for the drawing in the plan's units."""
    if getattr(plan, 'units', 'imperial') == 'metric':
        return f'{inches * MM_PER_IN:.2f} mm'
    return fmt_in(inches)


def angles(plan):
    """Beam angles from start to stop (inclusive) in steps of angle_step."""
    start, stop = sorted((plan.angle_start, plan.angle_stop))
    step = max(plan.angle_step or 1.0, 0.1)
    count = int(math.floor((stop - start) / step + 1e-9))
    return [start + i * step for i in range(count + 1)] + ([stop] if (stop - start) % step > 1e-6 else [])


def weld_outline(plan):
    """Fusion faces of the single-V weld, from the cap edge down to the root, for the -x side."""
    t = plan.thickness
    half_gap = (plan.root_gap or 0) / 2
    land = min(plan.root_face or 0, t)
    half_cap_prep = half_gap + (t - land) * math.tan(math.radians(plan.bevel_angle))
    return [(-half_cap_prep, 0.0), (-half_gap, t - land), (-half_gap, t)]


def cap_width(plan):
    """Cap width as entered, or the bevel opening plus 1/16" overlap on each side."""
    if plan.cap_width:
        return plan.cap_width
    return -2 * weld_outline(plan)[0][0] + 0.125


def index_offset(plan):
    """Wedge front to the weld centre line: as entered, else the weld toe (half the cap width)."""
    return plan.index_offset if plan.index_offset is not None else cap_width(plan) / 2


def exit_x(plan):
    """Beam exit (index) point: behind the wedge front by the exit point distance."""
    return -(index_offset(plan) + plan.exit_point)


def beam_path(plan, angle, x0=None):
    """(exit, back-wall bounce, top-surface return) points of one beam leaving the wedge at x0."""
    t = plan.thickness
    x0 = exit_x(plan) if x0 is None else x0
    run = t * math.tan(math.radians(angle))
    points = [(x0, 0.0), (x0 + run, t)]
    if plan.legs >= 2:
        points.append((x0 + 2 * run, 0.0))
    return points


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


def _related(plan, name):
    """A plan's probe_model / wedge_model, or None (also for unsaved plans built from a form)."""
    try:
        return getattr(plan, name, None)
    except ObjectDoesNotExist:
        return None


def part_velocity(plan, wedge):
    """Part velocity in in/µs for the wedge's wave type (L-wave wedges refract a longitudinal beam)."""
    if wedge is not None and wedge.wave_type == 'LW':
        block = _related(plan, 'sensitivity_block')
        return first_number(block.velocity_long if block else '') or STEEL_LONGITUDINAL
    return plan.shear_velocity or STEEL_SHEAR


def first_number(text):
    match = re.search(r'-?\d+(?:\.\d+)?', text or '')
    return float(match.group()) if match else None


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
    probe, wedge = _related(plan, 'probe_model'), _related(plan, 'wedge_model')
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
                  exact=not estimated, estimated=estimated, from_file=from_file, wedge_data=wedge_data)


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
    return Layout(wedge, probe, face, (x0, 0.0), {angle: x0 for angle in angles(plan)})


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


class _Canvas:
    def __init__(self, x_min, x_max, y_min, y_max, mirror):
        self.scale = WIDTH_PX * SUPERSAMPLE / (x_max - x_min)
        self.x_min, self.y_min, self.mirror = x_min, y_min, mirror
        self.size = (WIDTH_PX * SUPERSAMPLE, int((y_max - y_min) * self.scale))
        self.image = Image.new('RGB', self.size, 'white')
        self.draw = ImageDraw.Draw(self.image)

    def px(self, point):
        x, y = point
        u = (x - self.x_min) * self.scale
        if self.mirror:
            u = self.size[0] - u
        return (u, (y - self.y_min) * self.scale)

    def w(self, pixels):
        return max(1, round(pixels * SUPERSAMPLE))

    def line(self, points, fill, width=1.0):
        self.draw.line([self.px(p) for p in points], fill=fill, width=self.w(width))

    def polygon(self, points, fill=None, outline=None, width=1.0):
        self.draw.polygon([self.px(p) for p in points], fill=fill, outline=outline, width=self.w(width))

    def dashed(self, a, b, fill, dash=8, gap=6, width=1.0):
        (x1, y1), (x2, y2) = self.px(a), self.px(b)
        length = math.hypot(x2 - x1, y2 - y1)
        step = (dash + gap) * SUPERSAMPLE
        n = int(length // step) + 1
        for i in range(n):
            s = i * step / length
            e = min((i * step + dash * SUPERSAMPLE) / length, 1)
            self.draw.line([(x1 + (x2 - x1) * s, y1 + (y2 - y1) * s), (x1 + (x2 - x1) * e, y1 + (y2 - y1) * e)],
                           fill=fill, width=self.w(width))

    def text(self, point, text, size, fill=TEXT, anchor='mm'):
        self.draw.text(self.px(point), text, fill=fill, font=_font(size * SUPERSAMPLE), anchor=anchor)

    def arrow_head(self, tip, towards, fill):
        (tx, ty), (fx, fy) = self.px(tip), self.px(towards)
        ang = math.atan2(fy - ty, fx - tx)
        size = 9 * SUPERSAMPLE
        for d in (0.45, -0.45):
            self.draw.line([(tx, ty), (tx + size * math.cos(ang + d), ty + size * math.sin(ang + d))],
                           fill=fill, width=self.w(1.4))

    def png(self):
        out = self.image.resize((self.size[0] // SUPERSAMPLE, self.size[1] // SUPERSAMPLE), Image.LANCZOS)
        buffer = io.BytesIO()
        out.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()


def render_png(plan, side=1):
    """The scan plan drawing as PNG bytes; side 2 shows the probe on the other side of the weld."""
    t = plan.thickness
    lay = layout(plan)
    wedge, probe, (p1, p2) = lay.wedge, lay.probe, lay.face
    beams = [beam_path(plan, a, x0) for a, x0 in lay.exits.items()]
    half_cap = cap_width(plan) / 2
    cap_height = min(0.08, t * 0.3)
    root_height = min(0.05, t * 0.2)

    reach = max((p[0] for path in beams for p in path), default=half_cap)
    x_min = min(p[0] for p in wedge + probe) - 0.25
    x_max = max(half_cap + 0.35, min(reach, half_cap + 2.5) + 0.1)
    y_min = min(p[1] for p in wedge + probe) - 0.42  # room for the dimension and the caption
    y_max = t + root_height + 0.25
    c = _Canvas(x_min, x_max, y_min, y_max, mirror=(side == 2))

    # Plate
    c.polygon([(x_min, 0), (x_max, 0), (x_max, t), (x_min, t)], fill=PLATE_FILL)

    # Weld: fusion zone, cap and root beads
    faces = weld_outline(plan)
    mirrored = [(-x, y) for x, y in reversed(faces)]
    c.polygon(faces + mirrored, fill=WELD)
    cap = [(half_cap * math.cos(math.pi - i * math.pi / 40), -cap_height * math.sin(i * math.pi / 40)) for i in range(41)]
    c.polygon(cap, fill=WELD)
    root_half = max(-faces[-1][0] + 0.05, 0.06)
    root = [(root_half * math.cos(math.pi - i * math.pi / 40), t + root_height * math.sin(i * math.pi / 40)) for i in range(41)]
    c.polygon(root, fill=WELD)
    c.line(faces, WELD_LINE, 1.5)
    c.line(mirrored, WELD_LINE, 1.5)
    c.line(cap, WELD_LINE, 1)
    c.line(root, WELD_LINE, 1)

    # Plate surfaces drawn over the weld fill
    c.line([(x_min, 0), (-half_cap, 0)], PLATE, 1.5)
    c.line([(half_cap, 0), (x_max, 0)], PLATE, 1.5)
    c.line([(x_min, t), (-root_half, t)], PLATE, 1.5)
    c.line([(root_half, t), (x_max, t)], PLATE, 1.5)

    # Weld centre line
    c.dashed((0, -cap_height - 0.12), (0, t + root_height + 0.12), CENTRE_LINE, width=1)

    # Beams in the wedge: from the active aperture to each exit point (catalogue layout), or a
    # sketched fan from the probe face to the single entered exit point
    if lay.aperture:  # catalogue layout: rays from the active aperture
        wedge_rays = [(lay.source, (x0, 0.0)) for x0 in lay.exits.values()]
    else:
        wedge_rays = [((p1[0] + (p2[0] - p1[0]) * i / 8, p1[1] + (p2[1] - p1[1]) * i / 8), lay.source)
                      for i in range(9)]

    for path in beams:
        c.line(path, BEAM, 0.8)

    # Wedge and probe
    c.polygon(wedge, fill=WEDGE_FILL, outline=WEDGE_LINE, width=1.2)
    for ray in wedge_rays:
        c.line(ray, WEDGE_BEAM, 0.8)
    c.polygon(probe, fill=PROBE_FILL, outline=WEDGE_LINE, width=1.2)
    if lay.aperture:
        c.line(lay.aperture, BEAM, 3)

    # Index offset: wedge front to weld centre line
    front = -index_offset(plan)
    top = min(p[1] for p in wedge)
    dim_y = top - 0.12
    c.line([(front, top - 0.02), (front, dim_y - 0.08)], DIMENSION, 1)
    c.line([(0, -cap_height - 0.05), (0, dim_y - 0.08)], DIMENSION, 1)
    c.line([(front, dim_y), (0, dim_y)], DIMENSION, 1.2)
    c.arrow_head((front, dim_y), (0, dim_y), DIMENSION)
    c.arrow_head((0, dim_y), (front, dim_y), DIMENSION)
    c.draw.text(c.px((front / 2, dim_y - 0.03)), fmt_length(plan, index_offset(plan)), fill=DIMENSION, font=_font(19 * SUPERSAMPLE),
                anchor='mb', stroke_width=SUPERSAMPLE * 3, stroke_fill='white')

    # Labels
    corner = (x_min + 0.05, y_min + 0.08)  # mirrored to the right-hand corner on side 2
    label = f'{plan.angle_start:g}°–{plan.angle_stop:g}°  ·  t = {fmt_length(plan, t)}'
    probe_model, wedge_model = _related(plan, 'probe_model'), _related(plan, 'wedge_model')
    if probe_model or wedge_model:
        label += f'  ·  {probe_model or "probe?"} on {wedge_model or "wedge?"}'
    if lay.from_file:
        label += '  ·  wedge geometry from the .nde file'
    if lay.estimated:
        label += f'  ·  estimated: {", ".join(lay.estimated)}'
    c.draw.text(c.px(corner), label, fill=TEXT, font=_font(15 * SUPERSAMPLE), anchor='la' if side == 1 else 'ra')
    return c.png()
