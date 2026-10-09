"""
The scan plan drawing as a scene: the view's bounds and a list of shapes in part coordinates
(inches), in drawing order. Shapes name a style (plate, weld, beam, ...) rather than a colour, so
the Pillow renderer and a browser drawing can each colour them their own way.

Shape kinds: polygon (points, fill, stroke, width), line (points, stroke, width), dashed (a, b,
stroke, width), arrow (tip, towards, stroke), text (at, text, size, stroke, anchor, halo) and
cells (centres, size, fill: equal rectangles, e.g. the coverage gaps).
`group` says what a shape belongs to (probe: the wedge, probe and rays in the wedge, which move
together; beam; dimension; coverage) and `data` carries what it is (e.g. a beam's angle and sound
path) for the editor's interactive drawing. `meta` holds the numbers that drawing needs.
"""
import math
from dataclasses import asdict, dataclass, field

from .beams import fan
from .coverage import cell_size, coverage, flat_inspection_region, inspection_region
from .geometry import (
    back_wall, cap_edges, fmt_length, index_offset, mirror, od_radius, symmetric, toe, weld_faces, weld_thickness,
    wrap, wrap_path,
)
from .probe import at_position
from . import reflectors as reflector_shapes


@dataclass
class Scene:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    mirror: bool                  # side 2 (270 deg skew): drawn left-right flipped
    shapes: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def add(self, kind, **values):
        self.shapes.append({'kind': kind, **values})

    def as_dict(self):
        return asdict(self)


def build_scene(plan, side=1, position=1, analysis=False):
    """
    The scan plan drawing: side 1 is the 90 deg skew, side 2 the 270 deg skew (the probe on the
    other side of the weld); position 2 uses the second index offset. With `analysis` (the editor's
    live drawing, not the printed one) it also outlines the inspection volume (weld + HAZ) and
    shades what no ticked skew covers.
    """
    whole_plan = plan
    plan = at_position(plan, position)
    t = plan.thickness
    radius = od_radius(plan)            # None: a flat section
    beams = fan(plan)
    wedge, probe, traces = beams.wedge, beams.probe, beams.traces
    t_weld = weld_thickness(plan)
    # The weld as it is, turned round for a mirrored (270 deg) drawing when it isn't symmetric,
    # so it lands the right way round once the drawing is flipped
    flip = -1 if side == 2 and not symmetric(plan) else 1
    left, right = weld_faces(plan)
    if flip == -1:
        left, right = mirror(right), mirror(left)
    cap_left, cap_right = sorted(flip * x for x in cap_edges(plan))
    reach_toe = toe(plan)
    cap_height = plan.cap_height if getattr(plan, 'cap_height', None) else min(0.08, t_weld * 0.3)
    root_height = plan.root_height if getattr(plan, 'root_height', None) else min(0.05, t_weld * 0.2)

    reach = max((p[0] for beam in traces for p in beam.points), default=reach_toe)
    x_min = min(p[0] for p in wedge + probe) - 0.25
    beyond = 2.5 if radius is None else 1.5   # how far past the toe beams are drawn (less round a pipe)
    x_max = max(reach_toe + 0.35, min(reach, reach_toe + beyond) + 0.1)
    y_min = min(p[1] for p in wedge + probe) - 0.3  # room for the offset dimension
    y_max = max(t, t_weld + root_height) + 0.25
    if analysis:
        x_max = max(x_max, max(abs(x) for x, _ in inspection_region(plan)) + 0.1)

    # A curved section: everything laid out flat (x along the OD) is wrapped onto the pipe, and
    # the wall is drawn between the view's sides as distances along the OD
    def on_pipe(points):
        return wrap_path(plan, points)

    def closed(points):
        return points if radius is None else wrap_path(plan, points + points[:1])[:-1]

    s_min, s_max = x_min, x_max
    if radius is not None:
        s_min, s_max = (radius * math.asin(max(-1.0, min(1.0, x / radius))) for x in (x_min, x_max))
        wall_ends = [wrap(plan, s, t) for s in (s_min, s_max)]
        # Down to the wall at the view's sides; beams running on round the pipe leave the view
        y_max = max([y_max] + [y + 0.1 for _, y in wall_ends])

    scene = Scene(x_min, x_max, y_min, y_max, mirror=(side == 2), meta={
        'side': side, 'position': position, 'thickness': t, 'index_offset': index_offset(plan), 'toe': reach_toe,
        'units': getattr(plan, 'units', 'imperial'), 'legs': plan.legs, 'od_radius': radius,
        'lift_off': beams.lift_off,
    })

    # Plate (a flat section's down to its back wall, with any counterbore; or the pipe's wall)
    if radius is None:
        wall = back_wall(plan, x_min, x_max)
        scene.add('polygon', points=[(x_min, 0), (x_max, 0)] + wall[::-1], fill='plate_fill')
    else:
        scene.add('polygon', points=closed([(s_min, 0), (s_max, 0), (s_max, t), (s_min, t)]), fill='plate_fill')

    # Weld: fusion zone, cap and root beads
    right_up = right[::-1]   # root to cap
    scene.add('polygon', points=closed(left + right_up), fill='weld')
    centre, half_cap = (cap_left + cap_right) / 2, (cap_right - cap_left) / 2
    cap = [(centre + half_cap * math.cos(math.pi - i * math.pi / 40), -cap_height * math.sin(i * math.pi / 40))
           for i in range(41)]
    scene.add('polygon', points=closed(cap), fill='weld')
    root_half = max(max(-left[-1][0], right[-1][0]) + 0.05, 0.06)
    root = [(root_half * math.cos(math.pi - i * math.pi / 40), t_weld + root_height * math.sin(i * math.pi / 40))
            for i in range(41)]
    scene.add('polygon', points=closed(root), fill='weld')
    if analysis:  # gaps over the weld fill, under its outlines and the beams
        _add_coverage(scene, whole_plan, -1 if side == 2 else 1)
    scene.add('line', points=on_pipe(left), stroke='weld_line', width=1.5)
    scene.add('line', points=on_pipe(right_up), stroke='weld_line', width=1.5)
    scene.add('line', points=on_pipe(cap), stroke='weld_line', width=1)
    scene.add('line', points=on_pipe(root), stroke='weld_line', width=1)

    # Plate surfaces drawn over the weld fill
    if radius is None:
        scene.add('line', points=[(x_min, 0), (cap_left, 0)], stroke='plate', width=1.5)
        scene.add('line', points=[(cap_right, 0), (x_max, 0)], stroke='plate', width=1.5)
        scene.add('line', points=back_wall(plan, x_min, -root_half), stroke='plate', width=1.5)
        scene.add('line', points=back_wall(plan, root_half, x_max), stroke='plate', width=1.5)
    else:
        for line in ([(s_min, 0), (cap_left, 0)], [(cap_right, 0), (s_max, 0)],
                     [(s_min, t), (-root_half, t)], [(root_half, t), (s_max, t)]):
            scene.add('line', points=on_pipe(line), stroke='plate', width=1.5)

    # Weld centre line
    scene.add('dashed', a=(0, -cap_height - 0.12), b=(0, t + root_height + 0.12), stroke='centre_line', width=1)

    # Reflectors (the editor's drawing; the printed one only when asked): which beams meet each
    reflectors = []
    if (analysis or getattr(plan, 'print_reflectors', False)) and getattr(plan, 'reflectors', None):
        reflectors = reflector_shapes.shapes(plan, -1 if side == 2 else 1)
    beam_hits = [{} for _ in traces]                  # per beam: {reflector index: hit}
    for i, shape in enumerate(reflectors):
        for j, beam in enumerate(traces):
            found = reflector_shapes.hit(beam.points, shape)
            if found:
                beam_hits[j][i] = found

    for beam, hits in zip(traces, beam_hits):
        data = {'angle': beam.angle, 'sound_path': beam.sound_path, 'surfaces': beam.surfaces}
        if beam.refracted is not None:   # on a curved OD, the angle it really enters at
            data['refracted'] = beam.refracted
        if hits:
            data['hits'] = [{'label': reflectors[i].label, 'leg': h['leg'], 'sound_path': h['sound_path']}
                            for i, h in hits.items()]
        scene.add('line', points=beam.points, stroke='beam', width=0.8, group='beam', data=data)

    if reflectors:
        summaries = []
        for i, shape in enumerate(reflectors):
            met = [(traces[j].angle, hits[i]) for j, hits in enumerate(beam_hits) if i in hits]
            summary = reflector_shapes.summary(shape, met)
            summaries.append(summary)
            if summary['best']:   # the best beam, up to where it meets the reflector
                beam = next(traces[j] for j, hits in enumerate(beam_hits)
                            if i in hits and traces[j].angle == summary['best']['angle'])
                found = beam_hits[traces.index(beam)][i]
                path = beam.points[:found['leg']] + [found['point']]
                scene.add('line', points=path, stroke='reflector_beam', width=1.8, group='best',
                          data={'best_for': shape.label})
            if shape.centre is not None:
                scene.add('polygon', points=reflector_shapes.circle_points(shape), fill='reflector_fill',
                          stroke='reflector', width=1.5, group='reflector', data={'reflector': shape.label})
                tag = (shape.centre[0] + shape.radius, shape.centre[1] - shape.radius)
            else:
                scene.add('line', points=shape.path, stroke='reflector', width=2.5, group='reflector',
                          data={'reflector': shape.label})
                tag = min(shape.path, key=lambda p: p[1])
            scene.add('text', at=(tag[0] + 0.02, tag[1] - 0.02), text=shape.label, size=13, stroke='reflector',
                      anchor='lb', halo=True, group='reflector')
        scene.meta['reflectors'] = summaries

    # Wedge and probe (a flat wedge on a pipe: the couplant gap under its ends)
    if beams.couplant:
        scene.add('polygon', points=beams.couplant, fill='couplant', group='probe')
    scene.add('polygon', points=wedge, fill='wedge_fill', stroke='wedge_line', width=1.2, group='probe')
    for ray in beams.wedge_rays:
        scene.add('line', points=list(ray), stroke='wedge_beam', width=0.8, group='probe')
    scene.add('polygon', points=probe, fill='probe_fill', stroke='wedge_line', width=1.2, group='probe')
    if beams.aperture:
        scene.add('line', points=list(beams.aperture), stroke='beam', width=3, group='probe')

    # Index offset: wedge front to weld centre line (along the OD on a pipe)
    front = beams.front[0]
    top = min(p[1] for p in wedge)
    dim_y = top - 0.12
    dimension = {'stroke': 'dimension', 'group': 'dimension'}
    scene.add('line', points=[(front, top - 0.02), (front, dim_y - 0.08)], width=1, **dimension)
    scene.add('line', points=[(0, -cap_height - 0.05), (0, dim_y - 0.08)], width=1, **dimension)
    scene.add('line', points=[(front, dim_y), (0, dim_y)], width=1.2, **dimension)
    scene.add('arrow', tip=(front, dim_y), towards=(0, dim_y), **dimension)
    scene.add('arrow', tip=(0, dim_y), towards=(front, dim_y), **dimension)
    scene.add('text', at=(front / 2, dim_y - 0.03), text=fmt_length(plan, index_offset(plan)), size=19,
              anchor='mb', halo=True, data={'dimension': 'index offset'}, **dimension)
    scene.meta['dimension_y'] = dim_y

    # Part thickness: OD to ID behind the beams, labelled beside it: near the view's edge on a
    # plate; on a pipe (whose wall falls away at the edge) under the back of the wedge
    at = s_min + 0.12
    if radius is not None:
        back = min(x for x, _ in wedge)
        at = max(at, radius * math.asin(max(-1.0, min(1.0, back / radius))))
    outside, inside = wrap(plan, at, 0), wrap(plan, at, t)
    scene.add('line', points=[outside, inside], width=1.2, **dimension)
    scene.add('arrow', tip=outside, towards=inside, **dimension)
    scene.add('arrow', tip=inside, towards=outside, **dimension)
    middle = wrap(plan, at, t / 2)
    scene.add('text', at=(middle[0] + 0.04, middle[1]), text=f'Thk {fmt_length(plan, t)}', size=19,
              anchor='rm' if scene.mirror else 'lm', halo=True, data={'dimension': 'thickness'}, **dimension)
    return scene


def _add_coverage(scene, plan, sign):
    """
    The inspection volume's outline and its uncovered cells. Coverage is worked out on the weld
    as it is (the 270 deg skew's probe on the +x side); `sign` -1 flips it back for a mirrored
    drawing so it lands in place.
    """
    result = coverage(plan)
    gaps = [(float(x) * sign, float(y)) for x, y in zip(result.x[~result.hit], result.y[~result.hit])]
    if gaps:
        scene.add('cells', centres=gaps, size=cell_size(plan), fill='gap', group='gaps')   # shown with the Gaps toggle
    region = flat_inspection_region(plan)
    for a, b in zip(region, region[1:]):
        if a[1] != b[1]:   # the sides; the top and bottom are the plate's surfaces
            (ax, ay), (bx, by) = wrap(plan, *a), wrap(plan, *b)
            scene.add('dashed', a=(ax * sign, ay), b=(bx * sign, by), stroke='haz', width=1, group='coverage')
