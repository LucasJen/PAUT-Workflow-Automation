"""
The scan plan drawing as a scene: the view's bounds and a list of shapes in part coordinates
(inches), in drawing order. Shapes name a style (plate, weld, beam, ...) rather than a colour, so
the Pillow renderer and a browser drawing can each colour them their own way.

Shape kinds: polygon (points, fill, stroke, width), line (points, stroke, width), dashed (a, b,
stroke, width), arrow (tip, towards, stroke) and text (at, text, size, stroke, anchor, halo).
`data` carries what a shape is (e.g. a beam's angle and sound path) for hover readouts.
"""
import math
from dataclasses import asdict, dataclass, field

from .geometry import cap_width, fmt_length, index_offset, part, weld_outline
from .probe import at_position, layout
from .tracer import trace


@dataclass
class Scene:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    mirror: bool                  # side 2 (270 deg skew): drawn left-right flipped
    shapes: list = field(default_factory=list)

    def add(self, kind, **values):
        self.shapes.append({'kind': kind, **values})

    def as_dict(self):
        return asdict(self)


def build_scene(plan, side=1, position=1):
    """
    The scan plan drawing: side 1 is the 90 deg skew, side 2 the 270 deg skew (the probe on the
    other side of the weld); position 2 uses the second index offset.
    """
    plan = at_position(plan, position)
    t = plan.thickness
    lay = layout(plan)
    wedge, probe, (p1, p2) = lay.wedge, lay.probe, lay.face
    the_part = part(plan)
    traces = [trace(the_part, (x0, 0.0), angle, plan.legs) for angle, x0 in lay.exits.items()]
    half_cap = cap_width(plan) / 2
    cap_height = min(0.08, t * 0.3)
    root_height = min(0.05, t * 0.2)

    reach = max((p[0] for beam in traces for p in beam.points), default=half_cap)
    x_min = min(p[0] for p in wedge + probe) - 0.25
    x_max = max(half_cap + 0.35, min(reach, half_cap + 2.5) + 0.1)
    y_min = min(p[1] for p in wedge + probe) - 0.3  # room for the offset dimension
    y_max = t + root_height + 0.25
    scene = Scene(x_min, x_max, y_min, y_max, mirror=(side == 2))

    # Plate
    scene.add('polygon', points=[(x_min, 0), (x_max, 0), (x_max, t), (x_min, t)], fill='plate_fill')

    # Weld: fusion zone, cap and root beads
    faces = weld_outline(plan)
    mirrored = [(-x, y) for x, y in reversed(faces)]
    scene.add('polygon', points=faces + mirrored, fill='weld')
    cap = [(half_cap * math.cos(math.pi - i * math.pi / 40), -cap_height * math.sin(i * math.pi / 40))
           for i in range(41)]
    scene.add('polygon', points=cap, fill='weld')
    root_half = max(-faces[-1][0] + 0.05, 0.06)
    root = [(root_half * math.cos(math.pi - i * math.pi / 40), t + root_height * math.sin(i * math.pi / 40))
            for i in range(41)]
    scene.add('polygon', points=root, fill='weld')
    scene.add('line', points=faces, stroke='weld_line', width=1.5)
    scene.add('line', points=mirrored, stroke='weld_line', width=1.5)
    scene.add('line', points=cap, stroke='weld_line', width=1)
    scene.add('line', points=root, stroke='weld_line', width=1)

    # Plate surfaces drawn over the weld fill
    scene.add('line', points=[(x_min, 0), (-half_cap, 0)], stroke='plate', width=1.5)
    scene.add('line', points=[(half_cap, 0), (x_max, 0)], stroke='plate', width=1.5)
    scene.add('line', points=[(x_min, t), (-root_half, t)], stroke='plate', width=1.5)
    scene.add('line', points=[(root_half, t), (x_max, t)], stroke='plate', width=1.5)

    # Weld centre line
    scene.add('dashed', a=(0, -cap_height - 0.12), b=(0, t + root_height + 0.12), stroke='centre_line', width=1)

    # Beams in the wedge: from the active aperture to each exit point (catalogue layout), or a
    # sketched fan from the probe face to the single entered exit point
    if lay.aperture:
        wedge_rays = [(lay.source, (x0, 0.0)) for x0 in lay.exits.values()]
    else:
        wedge_rays = [((p1[0] + (p2[0] - p1[0]) * i / 8, p1[1] + (p2[1] - p1[1]) * i / 8), lay.source)
                      for i in range(9)]

    for beam in traces:
        scene.add('line', points=beam.points, stroke='beam', width=0.8,
                  data={'angle': beam.angle, 'sound_path': beam.sound_path, 'surfaces': beam.surfaces})

    # Wedge and probe
    scene.add('polygon', points=wedge, fill='wedge_fill', stroke='wedge_line', width=1.2)
    for ray in wedge_rays:
        scene.add('line', points=list(ray), stroke='wedge_beam', width=0.8)
    scene.add('polygon', points=probe, fill='probe_fill', stroke='wedge_line', width=1.2)
    if lay.aperture:
        scene.add('line', points=list(lay.aperture), stroke='beam', width=3)

    # Index offset: wedge front to weld centre line
    front = -index_offset(plan)
    top = min(p[1] for p in wedge)
    dim_y = top - 0.12
    scene.add('line', points=[(front, top - 0.02), (front, dim_y - 0.08)], stroke='dimension', width=1)
    scene.add('line', points=[(0, -cap_height - 0.05), (0, dim_y - 0.08)], stroke='dimension', width=1)
    scene.add('line', points=[(front, dim_y), (0, dim_y)], stroke='dimension', width=1.2)
    scene.add('arrow', tip=(front, dim_y), towards=(0, dim_y), stroke='dimension')
    scene.add('arrow', tip=(0, dim_y), towards=(front, dim_y), stroke='dimension')
    scene.add('text', at=(front / 2, dim_y - 0.03), text=fmt_length(plan, index_offset(plan)), size=19,
              stroke='dimension', anchor='mb', halo=True, data={'dimension': 'index offset'})
    return scene
