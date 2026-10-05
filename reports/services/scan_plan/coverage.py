"""
Coverage: how much of the inspection volume (the weld plus a heat-affected zone band each side)
the beam fans reach, and the index offset that reaches the most of it.

The volume is sampled on a grid. A sample is covered when it lies between two neighbouring beams
of a fan on the same leg (the fan is treated as continuous between its angles). Every ticked skew
at every probe position counts together: the 90 and 270 deg skews each cover part of the weld.
"""
import copy
from dataclasses import dataclass, field

import numpy as np

from .geometry import cap_width, part, weld_outline
from .probe import at_position, layout
from .tracer import trace

DEFAULT_HAZ = 0.25          # in, each side of the fusion faces
GRID_X, GRID_Y = 80, 40     # samples across and through the inspection volume's bounding box
SEARCH_STEP = 0.02          # in, between the index offsets tried
FULL = 0.999                # this fraction or more counts as full coverage


def haz_width(plan):
    value = getattr(plan, 'haz_width', None)
    return DEFAULT_HAZ if value is None else value


def drawings(plan):
    """[(position, side)] for each ticked skew: side 1 = 90 deg, side 2 = 270 deg."""
    out = []
    for position, ninety, two_seventy in ((1, 'skew_90', 'skew_270'), (2, 'skew_90_2', 'skew_270_2')):
        if position == 2 and plan.index_offset_2 is None:
            continue
        if getattr(plan, ninety):
            out.append((position, 1))
        if getattr(plan, two_seventy):
            out.append((position, 2))
    return out


def inspection_region(plan):
    """The weld and its HAZ bands as a polygon (the -x side's fusion face moved out by the HAZ)."""
    haz = haz_width(plan)
    side = [(x - haz, y) for x, y in weld_outline(plan)]
    return side + [(-x, y) for x, y in reversed(side)]


def _inside(x, y, polygon):
    """Boolean array: which of the points (x, y arrays) are inside the polygon (even-odd rule)."""
    inside = np.zeros(x.shape, bool)
    for (x1, y1), (x2, y2) in zip(polygon, polygon[-1:] + polygon[:-1]):
        crosses = (y1 > y) != (y2 > y)
        if not crosses.any():
            continue
        with np.errstate(divide='ignore', invalid='ignore'):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= crosses & (x < x_cross)
    return inside


def _grid(plan):
    """Cell edges across (x) and through (y) the inspection volume's bounding box."""
    region = inspection_region(plan)
    xs, ys = [p[0] for p in region], [p[1] for p in region]
    return np.linspace(min(xs), max(xs), GRID_X + 1), np.linspace(min(ys), max(ys), GRID_Y + 1)


def cell_size(plan):
    """(width, height) of one sample's grid cell, in inches."""
    gx, gy = _grid(plan)
    return float(gx[1] - gx[0]), float(gy[1] - gy[0])


def samples(plan):
    """(x, y) arrays of the grid points inside the inspection volume (cell centres)."""
    region = inspection_region(plan)
    gx, gy = _grid(plan)
    x, y = np.meshgrid((gx[:-1] + gx[1:]) / 2, (gy[:-1] + gy[1:]) / 2)
    x, y = x.ravel(), y.ravel()
    keep = _inside(x, y, region)
    return x[keep], y[keep]


def fan(plan, side=1, position=1):
    """The areas a fan sweeps: one polygon per leg between each pair of neighbouring beams."""
    plan = at_position(plan, position)
    the_part = part(plan)
    beams = [trace(the_part, (x0, 0.0), angle, plan.legs).points for angle, x0 in layout(plan).exits.items()]
    sign = -1 if side == 2 else 1
    areas = []
    for a, b in zip(beams, beams[1:]):
        for leg in range(min(len(a), len(b)) - 1):
            area = [a[leg], a[leg + 1], b[leg + 1], b[leg]]
            areas.append([(sign * x, y) for x, y in area])
    return areas


def covered(plan, x, y, side=1, position=1):
    """Boolean array: which sample points the fan at (side, position) reaches."""
    hit = np.zeros(x.shape, bool)
    for area in fan(plan, side, position):
        hit |= _inside(x, y, area)
    return hit


@dataclass
class Coverage:
    x: object                   # sample points (numpy arrays, inches)
    y: object
    hit: object                 # which samples a fan reaches
    by_drawing: dict = field(default_factory=dict)   # {(position, side): fraction it covers alone}

    @property
    def fraction(self):
        return float(self.hit.mean()) if self.hit.size else 0.0

    @property
    def full(self):
        return self.fraction >= FULL


def coverage(plan):
    """How much of the inspection volume the ticked skews at the plan's probe positions cover."""
    x, y = samples(plan)
    hit = np.zeros(x.shape, bool)
    by_drawing = {}
    for position, side in drawings(plan):
        reach = covered(plan, x, y, side, position)
        by_drawing[(position, side)] = float(reach.mean()) if reach.size else 0.0
        hit |= reach
    return Coverage(x, y, hit, by_drawing)


@dataclass
class Suggestion:
    offset: float               # the middle of the widest run of offsets that cover the most
    low: float                  # that run's ends: any offset between them covers as much
    high: float
    fraction: float
    second_offset: float = None     # when one offset can't cover it all: the best pair
    pair_fraction: float = None


def suggest_offset(plan):
    """
    The index offset (wedge front to weld centre line) that covers the most of the inspection
    volume with the plan's first-position skews (both when none is ticked), searched from the weld
    toe outwards; and, when no single offset covers it all, the best pair of offsets.
    """
    sides = [side for side, name in ((1, 'skew_90'), (2, 'skew_270')) if getattr(plan, name)] or [1, 2]
    x, y = samples(plan)
    toe = np.ceil(cap_width(plan) / 2 * 1e4) / 1e4      # rounded up: never onto the cap
    reach = plan.thickness * plan.legs * 3 + 1.0      # well past where a 70 deg beam's legs end
    offsets = np.round(np.arange(toe, toe + reach, SEARCH_STEP), 4)
    trial = copy.copy(plan)
    masks = []
    for offset in offsets:
        trial.index_offset = float(offset)
        hit = np.zeros(x.shape, bool)
        for side in sides:
            hit |= covered(trial, x, y, side)
        masks.append(hit)
        if not hit.any() and any(m.any() for m in masks):   # moved out of reach: further only misses
            break
    offsets = offsets[:len(masks)]
    fractions = np.array([m.mean() if m.size else 0.0 for m in masks])
    best = fractions.max()

    # Widest run of neighbouring offsets that all reach the best coverage
    runs, start = [], None
    for i, good in enumerate(np.append(fractions >= best - 1e-9, False)):
        if good and start is None:
            start = i
        elif not good and start is not None:
            runs.append((start, i - 1))
            start = None
    low, high = max(runs, key=lambda run: run[1] - run[0])
    suggestion = Suggestion(float(offsets[(low + high) // 2]), float(offsets[low]), float(offsets[high]), float(best))

    if best < FULL:
        stack = np.array(masks)
        best_pair, pair_fraction = None, best
        for i in range(len(masks)):
            together = (stack[i + 1:] | stack[i]).mean(axis=1)
            if together.size and together.max() > pair_fraction + 1e-9:
                pair_fraction = float(together.max())
                best_pair = (i, i + 1 + int(together.argmax()))
        if best_pair:
            suggestion.offset, suggestion.second_offset = (float(offsets[k]) for k in best_pair)
            suggestion.low = suggestion.high = suggestion.offset
            suggestion.pair_fraction = pair_fraction
    return suggestion

