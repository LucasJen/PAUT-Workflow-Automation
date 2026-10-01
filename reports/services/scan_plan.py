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

from PIL import Image, ImageDraw, ImageFont

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


def exit_x(plan):
    """Beam exit (index) point: behind the wedge front by the exit point distance."""
    return -(plan.index_offset + plan.exit_point)


def beam_path(plan, angle):
    """(exit, back-wall bounce, top-surface return) points of one beam."""
    t = plan.thickness
    x0 = exit_x(plan)
    run = t * math.tan(math.radians(angle))
    points = [(x0, 0.0), (x0 + run, t)]
    if plan.legs >= 2:
        points.append((x0 + 2 * run, 0.0))
    return points


def _wedge(plan):
    """(wedge polygon, probe polygon, probe face centre, probe face end points)."""
    a = math.radians(plan.wedge_angle)
    x0 = exit_x(plan)
    front = -plan.index_offset
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
    wedge, probe, centre, (p1, p2) = _wedge(plan)
    beams = [beam_path(plan, a) for a in angles(plan)]
    half_cap = cap_width(plan) / 2
    cap_height = min(0.08, t * 0.3)
    root_height = min(0.05, t * 0.2)

    reach = max(p[0] for path in beams for p in path)
    x_min = min(p[0] for p in wedge) - 0.25
    x_max = max(half_cap + 0.35, min(reach, half_cap + 2.5) + 0.1)
    y_min = min(p[1] for p in wedge + probe) - 0.3
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

    # Beams: inside the wedge, then in the part
    exit_point = (exit_x(plan), 0.0)
    for i in range(9):
        f = i / 8
        c.line([(p1[0] + (p2[0] - p1[0]) * f, p1[1] + (p2[1] - p1[1]) * f), exit_point], WEDGE_BEAM, 0.8)
    for path in beams:
        c.line(path, BEAM, 0.8)

    # Wedge and probe
    c.polygon(wedge, fill=WEDGE_FILL, outline=WEDGE_LINE, width=1.2)
    for i in range(9):  # wedge beams again, over the wedge fill
        f = i / 8
        c.line([(p1[0] + (p2[0] - p1[0]) * f, p1[1] + (p2[1] - p1[1]) * f), exit_point], WEDGE_BEAM, 0.8)
    c.polygon(probe, fill=PROBE_FILL, outline=WEDGE_LINE, width=1.2)

    # Index offset: wedge front to weld centre line
    front = -plan.index_offset
    top = min(p[1] for p in wedge)
    dim_y = top - 0.12
    c.line([(front, top - 0.02), (front, dim_y - 0.08)], DIMENSION, 1)
    c.line([(0, -cap_height - 0.05), (0, dim_y - 0.08)], DIMENSION, 1)
    c.line([(front, dim_y), (0, dim_y)], DIMENSION, 1.2)
    c.arrow_head((front, dim_y), (0, dim_y), DIMENSION)
    c.arrow_head((0, dim_y), (front, dim_y), DIMENSION)
    c.draw.text(c.px((front / 2, dim_y - 0.03)), fmt_in(plan.index_offset), fill=DIMENSION, font=_font(19 * SUPERSAMPLE),
                anchor='mb', stroke_width=SUPERSAMPLE * 3, stroke_fill='white')

    # Labels
    corner = (x_min + 0.05, y_min + 0.08)  # mirrored to the right-hand corner on side 2
    label = f'{plan.angle_start:g}°–{plan.angle_stop:g}°  ·  t = {fmt_in(t)}'
    c.draw.text(c.px(corner), label, fill=TEXT, font=_font(15 * SUPERSAMPLE), anchor='la' if side == 1 else 'ra')
    return c.png()
