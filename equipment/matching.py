"""
Finds the catalogue probe and wedge for the ones an instrument file (OmniScan .nde) used.

The file gives the probe and wedge names and, for the wedge, its geometry. Names are compared
ignoring case, spaces, dashes and underscores, and ignoring the IHC / IH / IC (irrigation and
carbide wear pads) and SA designations, which don't change the wedge geometry; among same-named
variants the file's geometry picks one. When the name doesn't match, the base name (SA1-N60S) and
then the geometry pick among the wedges that fit the probe. A wedge that matches by name but whose
geometry differs from the file is still linked, with the differences listed so the user can decide.
"""
import re
from dataclasses import dataclass, field

from .compat import probe_spec, wedges_for_probe
from .models import ProbeModel, WedgeModel

# Geometry closer than this counts as the same wedge
TOLERANCES = {
    'wedge_angle': 0.5,             # degrees
    'velocity': 20.0,               # m/s
    'primary_offset': 0.75,         # mm
    'first_element_height': 0.75,   # mm
}
# Wedge name designations that don't change its geometry: irrigation / carbide pads and SA
IGNORED_DESIGNATIONS = {'ihc', 'ih', 'ic', 'sa'}
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
    suggestion: object = None       # another catalogue wedge whose geometry does match the file


def normalize(name):
    return re.sub(r'[\s\-_]+', '', (name or '').lower())


def base_name(name):
    """'SA1-N60S' for 'SA1-N60S 10L32' or 'SA1-N60S_10L32'."""
    return re.split(r'[\s_]', (name or '').strip(), maxsplit=1)[0]


def family_name(name):
    """
    The name without the designations that don't change the geometry:
    'SA1-N60S-IHC-SA 10L32' and 'SA1-N60S 10L32' are both 'sa1n60s10l32'.
    """
    parts = re.split(r'([\s_])', (name or '').strip(), maxsplit=1)
    tokens = parts[0].split('-')
    kept = tokens[:2] + [t for t in tokens[2:] if t.lower() not in IGNORED_DESIGNATIONS]
    return normalize('-'.join(kept) + ''.join(parts[1:]))


def match_probe(file_probe):
    """The catalogue probe for the file's probe fields (from importers.probe_from_nde)."""
    name = normalize(file_probe.get('model'))
    if name:
        for probe in ProbeModel.objects.all():
            if normalize(probe.model) == name:
                return Match(probe, 'by name')
    # Same series and the same frequency, array type, element count and pitch (what the file
    # doesn't say isn't compared)
    file_like = ProbeModel(model=file_probe.get('model') or '', frequency=file_probe.get('frequency'),
                           elements=file_probe.get('elements'))
    wanted = probe_spec(file_like)
    pitch = file_probe.get('pitch')
    candidates = []
    for probe in ProbeModel.objects.filter(series__iexact=file_probe.get('series') or ''):
        have = probe_spec(probe)
        if any(w is not None and h is not None and w != h for w, h in zip(wanted, have)):
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
        differences = geometry_differences(wedge, file_wedge)
        suggestion = _closest_geometry(file_wedge, [w for w in candidates if w != wedge]) if differences else None
        return Match(wedge, how, differences, suggestion)

    # By name, IHC / -SA variants included: the one whose geometry is closest to the file's (the
    # exact name on a tie). Skipped for an entry without geometry when the base-name variants
    # below have it (OmniScan may call the wedge just 'SA1-N60S'; the library has 'SA1-N60S 10L32'...)
    name = normalize(file_wedge.get('model'))
    family = family_name(file_wedge.get('model'))
    by_name = None
    if family:
        pool = candidates + [w for w in wedges if w not in candidates]
        same = [w for w in pool if family_name(w.model) == family]
        if same:
            def rank(w):
                distance = _distance(w, file_wedge)
                return (distance is None, distance or 0, normalize(w.model) != name, len(w.model))
            by_name = min(same, key=rank)
    if by_name is not None and (by_name.has_geometry or not _has_file_geometry(file_wedge)):
        how = 'by name' if normalize(by_name.model) == name else 'by name (IHC / SA designation ignored)'
        return found(by_name, how)

    # Same base name (SA1-N60S), the variant with the closest geometry
    base = normalize(base_name(file_wedge.get('model')))
    same_base = [w for w in candidates if base and normalize(base_name(w.model)) == base and w.has_geometry]
    if same_base:
        # Closest geometry; on a tie (e.g. only the wedge angle known) the plain variant, not R / -IHC
        ranked = sorted(same_base, key=lambda w: (_distance(w, file_wedge) is None, _distance(w, file_wedge) or 0,
                                                  len(w.model), w.model))
        how = f'closest geometry among {base_name(file_wedge["model"])} variants' if len(same_base) > 1 \
            else f'by base name {base_name(file_wedge["model"])}'
        return found(ranked[0], how)

    if by_name is not None:
        return found(by_name, 'by name')

    closest = _closest_geometry(file_wedge, candidates)
    return found(closest, 'by geometry') if closest is not None else Match()


def _closest_geometry(file_wedge, wedges):
    """
    The wedge whose geometry is within tolerance of the file's, closest first; only when both sides
    have the complete geometry (a wedge angle alone would match any wedge of that angle).
    """
    if not all(file_wedge.get(name) is not None for name in TOLERANCES):
        return None
    near = [(d, w) for w in wedges if w.has_geometry and (d := _distance(w, file_wedge)) is not None and d <= 1]
    return min(near, key=lambda pair: (pair[0], len(pair[1].model)))[1] if near else None


def _has_file_geometry(file_wedge):
    return any(file_wedge.get(name) is not None for name in TOLERANCES)
