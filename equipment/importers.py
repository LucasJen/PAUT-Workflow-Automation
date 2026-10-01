"""
Probe and wedge catalogue imports from instrument and modelling files.

Each reader takes an uploaded file and returns (probes, wedges): lists of field dicts in the
catalogue's units (mm, MHz, m/s, degrees), keyed by `model`. Add a format by writing a reader
and listing it in READERS by file extension.
"""
from reports.services.nde_parser import NdeError, read_nde


class CatalogueImportError(Exception):
    """The file could not be read as a probe / wedge source."""


def _mm(metres):
    return None if metres is None else round(metres * 1000, 3)


def _probe_from_nde(probe):
    tech = probe.get('phasedArrayLinear') or {}
    primary, secondary = tech.get('primaryAxis') or {}, tech.get('secondaryAxis') or {}
    length, gap = primary.get('elementLength'), primary.get('elementGap') or 0
    frequency = tech.get('centralFrequency')
    values = {
        'model': probe.get('model'),
        'series': probe.get('serie'),
        'frequency': round(frequency / 1e6, 3) if frequency else None,
        'elements': primary.get('elementQuantity'),
        'pitch': _mm(length + gap) if length is not None else None,
        'elevation': _mm(secondary.get('elementLength')),
        'length': _mm(primary.get('casingLength')),
    }
    return {k: v for k, v in values.items() if v not in (None, '')}


def _wedge_from_nde(wedge):
    angle_beam = wedge.get('angleBeamWedge') or {}
    mounting = (angle_beam.get('mountingLocations') or [{}])[0]
    values = {
        'model': wedge.get('model'),
        'probe_series': (wedge.get('serie') or '').removeprefix('S') or None,
        'length': _mm(angle_beam.get('length')),
        'width': _mm(angle_beam.get('width')),
        'height': _mm(angle_beam.get('height')),
        'velocity': angle_beam.get('longitudinalVelocity'),
        'wedge_angle': mounting.get('wedgeAngle'),
        'primary_offset': _mm(mounting.get('primaryOffset')),
        'first_element_height': _mm(mounting.get('tertiaryOffset')),
    }
    return {k: v for k, v in values.items() if v not in (None, '')}


def read_nde_catalogue(uploaded):
    """Probes and wedges used in an OmniScan / OmniPC .nde file."""
    try:
        setup, _ = read_nde(uploaded)
    except NdeError as e:
        raise CatalogueImportError(str(e)) from e
    probes = [_probe_from_nde(p) for p in setup.get('probes') or [] if p.get('model')]
    wedges = [_wedge_from_nde(w) for w in setup.get('wedges') or [] if w.get('model')]
    return probes, wedges


READERS = {
    '.nde': read_nde_catalogue,
}


def read_catalogue_file(uploaded):
    """(probes, wedges) from any supported file; raises CatalogueImportError for unsupported or bad files."""
    name = (uploaded.name or '').lower()
    for extension, reader in READERS.items():
        if name.endswith(extension):
            return reader(uploaded)
    supported = ', '.join(sorted(READERS))
    raise CatalogueImportError(f'"{uploaded.name}" is not a supported file. Supported: {supported}.')
