"""
Draws a vessel scene (scene.py) with Pillow: the PNG shown in the editors and printed on a
report's Drawings page. Drawn three times larger, then scaled down for smooth lines.
"""
import io
import math

from PIL import Image, ImageDraw

from ..scan_plan.render import _font
from .scene import PX_PER_UNIT

SUPERSAMPLE = 3
MAX_PX = 2400               # longest side; a very long drawing is scaled down to fit

COLOURS = {
    'outline': (35, 35, 35),
    'paper': (255, 255, 255),
    'flange': (236, 236, 236),
    'support': (214, 214, 214),
    'hidden': (110, 110, 110),
    'centre': (130, 130, 130),
    'leader': (60, 60, 60),
    'text': (25, 25, 25),
    'label': (90, 90, 90),
    'seam': (200, 25, 25),
    'coverage': (255, 214, 140),
    'coverage_line': (225, 110, 0),
    'coverage_text': (150, 70, 0),
    'box': (215, 20, 20),
}


def _bold_font(size):
    from PIL import ImageFont
    for name in ('arialbd.ttf', 'Arial Bold.ttf', 'DejaVuSans-Bold.ttf'):
        for folder in ('', r'C:\Windows\Fonts'):
            try:
                return ImageFont.truetype(f'{folder}\\{name}' if folder else name, size)
            except OSError:
                continue
    return _font(size)


class _Canvas:
    def __init__(self, scene):
        width = (scene.x_max - scene.x_min) * PX_PER_UNIT
        height = (scene.y_max - scene.y_min) * PX_PER_UNIT
        fit = min(1.0, MAX_PX / max(width, height))
        self.k = PX_PER_UNIT * fit * SUPERSAMPLE          # pixels per unit, supersampled
        self.text_k = fit * SUPERSAMPLE                     # text sizes are in px at full size
        self.x_min, self.y_min = scene.x_min, scene.y_min
        self.size = (max(1, round(width * fit)) * SUPERSAMPLE, max(1, round(height * fit)) * SUPERSAMPLE)
        self.image = Image.new('RGB', self.size, 'white')
        self.draw = ImageDraw.Draw(self.image)

    def px(self, point):
        x, y = point
        return ((x - self.x_min) * self.k, (y - self.y_min) * self.k)

    def w(self, width):
        return max(1, round(width * self.text_k))

    def polygon(self, points, fill, stroke, width, dashed=False):
        pts = [self.px(p) for p in points]
        if fill:
            self.draw.polygon(pts, fill=fill)
        if stroke and width:
            if dashed:
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    self.dashed(a, b, stroke, width)
            else:
                self.draw.line(pts + pts[:1], fill=stroke, width=self.w(width), joint='curve')

    def line(self, points, stroke, width):
        self.draw.line([self.px(p) for p in points], fill=stroke, width=self.w(width), joint='curve')

    def dashed(self, a, b, stroke, width, dash=7, gap=4):
        (x1, y1), (x2, y2) = a, b
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            return
        step = (dash + gap) * self.text_k
        n = int(length // step) + 1
        for i in range(n):
            s = i * step / length
            e = min((i * step + dash * self.text_k) / length, 1)
            self.draw.line([(x1 + (x2 - x1) * s, y1 + (y2 - y1) * s), (x1 + (x2 - x1) * e, y1 + (y2 - y1) * e)],
                           fill=stroke, width=self.w(width))

    def circle(self, at, radius, fill, stroke, width, dashed=False):
        x, y = self.px(at)
        r = radius * self.k
        if dashed:
            points = [(x + r * math.cos(t), y + r * math.sin(t)) for t in (2 * math.pi * k / 24 for k in range(25))]
            for k in range(0, 24, 2):
                self.draw.line(points[k:k + 2], fill=stroke, width=self.w(width))
            return
        self.draw.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline=stroke if width else None,
                          width=self.w(width) if width else 0)

    def text(self, at, text, size, colour, anchor, bold, halo):
        font = (_bold_font if bold else _font)(max(1, round(size * self.text_k)))
        extra = {'stroke_width': round(3 * self.text_k), 'stroke_fill': 'white'} if halo else {}
        self.draw.text(self.px(at), str(text), fill=colour, font=font, anchor=anchor, **extra)

    def png(self):
        out = self.image.resize((self.size[0] // SUPERSAMPLE, self.size[1] // SUPERSAMPLE), Image.LANCZOS)
        buffer = io.BytesIO()
        out.save(buffer, format='PNG', optimize=True)
        return buffer.getvalue()


def render_scene(scene):
    """PNG bytes of a vessel scene."""
    c = _Canvas(scene)
    colour = COLOURS.get
    for shape in scene.shapes:
        kind = shape['kind']
        if kind == 'polygon':
            c.polygon(shape['points'], colour(shape.get('fill')), colour(shape.get('stroke')), shape.get('width', 1),
                      shape.get('dashed', False))
        elif kind == 'line':
            c.line(shape['points'], colour(shape.get('stroke')), shape.get('width', 1))
        elif kind == 'dashed':
            pts = [c.px(p) for p in shape['points']]
            for a, b in zip(pts, pts[1:]):
                c.dashed(a, b, colour(shape.get('stroke')), shape.get('width', 1), dash=14, gap=4)
        elif kind == 'circle':
            c.circle(shape['at'], shape['radius'], colour(shape.get('fill')), colour(shape.get('stroke')),
                     shape.get('width', 1), shape.get('dashed', False))
        elif kind == 'text':
            c.text(shape['at'], shape['text'], shape['size'], colour(shape.get('colour')) or COLOURS['text'],
                   shape.get('anchor', 'mm'), shape.get('bold', False), shape.get('halo', False))
    return c.png()
