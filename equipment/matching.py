"""
Finds the catalogue probe and wedge for the ones an instrument file (OmniScan .nde) used.

The file gives the probe and wedge names and, for the wedge, its geometry. Names are compared
ignoring case, spaces, dashes and underscores; when a wedge name doesn't match exactly, its base
name (SA1-N60S) and then its geometry pick among the wedges that fit the probe. A wedge that
matches by name but whose geometry differs from the file is still linked, with the differences
listed so the user can decide.
"""
import re
from dataclasses import dataclass, field

from .compat import probe_spec, wedges_for_probe
from .models import ProbeModel, WedgeModel

# Geometry closer than this counts as the same wedge
TOLERANCES = {
    'wedge_angle': 0.3,             # degrees
    'velocity': 20.0,               # m/s
    'primary_offset': 0.5,          # mm
    'first_element_height': 0.5,    # mm
}
GEOMETRY_LABELS = {
    'wedge_angle': ('wedge angle', '°'),
    'velocity': ('wedge velocity', ' m/s'),
    'primary_offset': ('primary offset', ' mm'),
    'first_element_height': ('first element height', ' mm'),
}
PITCH_TOLERANCE = 0.02              # mm


@dataclass
class Match:
    item: object = None             # ProbeModel / WedgeModel, or None
    how: str = ''                   # e.g. 'by name', 'closest geometry among SA1-N60S variants'
    differences: list = field(default_factory=list)   # [(label, catalogue text, file text)]


def normalize(name):
    return re.sub(r'[\s\-_]+', '', (name or '').lower())


def base_name(name):
    """'SA1-N60S' for 'SA1-N60S 10L32' or 'SA1-N60S_10L32'."""
    return re.split(r'[\s_]', (name or '').strip(), maxsplit=1)[0]


def match_probe(file_probe):
    """The catalogue probe for the file's probe fields (from importers.probe_from_nde)."""
    name = normalize(file_probe.get('model'))
    if name:
        for probe in ProbeModel.objects.all():
            if normalize(probe.model) == name:
                return Match(probe, 'by name')
    # Same series and the same frequency, array type, element count and pitch
    file_like = ProbeModel(model=file_probe.get('model') or '', frequency=file_probe.get('frequency'),
                           elements=file_probe.get('elements'))
    wanted = probe_spec(file_like)
    pitch = file_probe.get('pitch')
    candidates = []
    for probe in ProbeModel.objects.filter(series__iexact=file_probe.get('series') or ''):
        if probe_spec(probe) != wanted:
            continue
        if pitch is not None and probe.pitch is not None and abs(probe.pitch - pitch) > PITCH_TOLERANCE:
            continue
        candidates.append(probe)
    if len(candidates) == 1:
        return Match(candidates[0], 'by frequency, elements and pitch')
    return Match()


def _distance(wedge, file_wedge):
    """How far a catalogue wedge's geometry is from the file's, in tolerance units (None if unknown)."""
    parts = []
    for name, tolerance in TOLERANCES.items():
        mine, theirs = getattr(wedge, name), file_wedge.get(name)
        if mine is None or theirs is None:
            continue
        parts.append(abs(mine - theirs) / tolerance)
    return max(parts) if parts else None


def geometry_differences(wedge, file_wedge):
    """[(label, catalogue text, file text)] for geometry outside tolerance."""
    out = []
    for name, tolerance in TOLERANCES.items():
        mine, theirs = getattr(wedge, name), file_wedge.get(name)
        if mine is None or theirs is None or abs(mine - theirs) <= tolerance:
            continue
        label, unit = GEOMETRY_LABELS[name]
        out.append((label, f'{mine:g}{unit}', f'{theirs:g}{unit}'))
    return out


def match_wedge(file_wedge, probe=None):
    """The catalogue wedge for the file's wedge fields (from importers.wedge_from_nde)."""
    wedges = list(WedgeModel.objects.all())
    candidates = wedges_for_probe(probe, wedges) if probe is not None else wedges

    def found(wedge, how):
        return Match(wedge, how, geometry_differences(wedge, file_wedge))

    name = normalize(file_wedge.get('model'))
    if name:
        for wedge in candidates + [w for w in wedges if w not in candidates]:
            if normalize(wedge.model) == name:
                return found(wedge, 'by name')

    # Same base name (SA1-N60S), the variant with the closest geometry
    base = normalize(base_name(file_wedge.get('model')))
    same_base = [w for w in candidates if base and normalize(base_name(w.model)) == base]
    if same_base:
        ranked = sorted(same_base, key=lambda w: (_distance(w, file_wedge) is None, _distance(w, file_wedge) or 0))
        how = f'closest geometry among {base_name(file_wedge["model"])} variants' if len(same_base) > 1 \
            else f'by base name {base_name(file_wedge["model"])}'
        return found(ranked[0], how)

    # Geometry alone, within tolerance
    near = [(d, w) for w in candidates if (d := _distance(w, file_wedge)) is not None and d <= 1]
    if near:
        return found(min(near, key=lambda pair: pair[0])[1], 'by geometry')
    return Match()
