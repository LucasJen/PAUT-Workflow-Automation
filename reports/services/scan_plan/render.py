"""
Draws a scene (scene.py) with Pillow as the PNG printed on the scan plan page and the Excel report.
"""
import io
import math
import os

from PIL import Image, ImageDraw, ImageFont

from .scene import build_scene

WIDTH_PX = 1100
SUPERSAMPLE = 3                       # drawn large, then scaled down for smooth lines

COLOURS = {
    'plate': (90, 90, 90),
    'plate_fill': (250, 250, 250),
    'weld': (205, 205, 205),
    'weld_line': (150, 150, 150),
    'wedge_fill': (226, 228, 248),
    'wedge_line': (60, 60, 80),
    'probe_fill': (238, 240, 252),
    'beam': (20, 40, 230),
    'wedge_beam': (120, 140, 240),
    'dimension': (0, 120, 0),
    'text': (40, 40, 40),
    'centre_line': (120, 120, 120),
    'gap': (248, 180, 180),
    'haz': (200, 110, 0),
    'couplant': (255, 226, 150),
    'reflector': (200, 20, 20),
    'reflector_fill': (255, 205, 205),
    'reflector_beam': (240, 120, 0),
}


def _font(size):
    for name in ('arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf'):
        for folder in ('', os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')):
            try:
                return ImageFont.truetype(os.path.join(folder, name) if folder else name, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _colour(name):
    return COLOURS[name] if name else None


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

    def text(self, point, text, size, fill, anchor='mm', halo=False):
        extra = {'stroke_width': SUPERSAMPLE * 3, 'stroke_fill': 'white'} if halo else {}
        self.draw.text(self.px(point), text, fill=fill, font=_font(size * SUPERSAMPLE), anchor=anchor, **extra)

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


def render_scene(scene):
    """PNG bytes of a scene."""
    c = _Canvas(scene.x_min, scene.x_max, scene.y_min, scene.y_max, scene.mirror)
    for shape in scene.shapes:
        kind, stroke = shape['kind'], _colour(shape.get('stroke'))
        if kind == 'polygon':
            c.polygon(shape['points'], fill=_colour(shape.get('fill')), outline=stroke, width=shape.get('width', 1.0))
        elif kind == 'line':
            c.line(shape['points'], stroke, shape.get('width', 1.0))
        elif kind == 'dashed':
            c.dashed(shape['a'], shape['b'], stroke, width=shape.get('width', 1.0))
        elif kind == 'cells':
            width, height = shape['size']
            for x, y in shape['centres']:
                c.polygon([(x - width / 2, y - height / 2), (x + width / 2, y - height / 2),
                           (x + width / 2, y + height / 2), (x - width / 2, y + height / 2)],
                          fill=_colour(shape['fill']))
        elif kind == 'arrow':
            c.arrow_head(shape['tip'], shape['towards'], stroke)
        elif kind == 'text':
            c.text(shape['at'], shape['text'], shape['size'], stroke or COLOURS['text'], shape.get('anchor', 'mm'),
                   shape.get('halo', False))
    return c.png()


def render_png(plan, side=1, position=1, analysis=False):
    """
    The scan plan drawing as PNG bytes: side 1 is the 90 deg skew, side 2 the 270 deg skew (the
    probe on the other side of the weld); position 2 uses the second index offset. `analysis` adds
    the coverage marks for the editor.
    """
    return render_scene(build_scene(plan, side, position, analysis))
