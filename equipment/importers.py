"""
Probe and wedge catalogue imports from instrument and modelling files.

Each reader takes an uploaded file and returns (probes, wedges): lists of field dicts in the
catalogue's units (mm, MHz, m/s, degrees), keyed by `model`. Add a format by writing a reader
and listing it in READERS by file extension. apply_catalogue() saves what a reader returns.

Supported: OmniScan / OmniPC .nde files (the probe and wedge a scan used) and the ES Beamtool
library exports PATransducers.csv and PAWedges.csv.
"""
import csv
import io
import re

from django.db import transaction

from reports.services.nde_parser import NdeError, read_nde

from .compat import BEAMTOOL_SOURCE
from .models import ProbeModel, WedgeModel


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


# ── ES Beamtool library exports (PATransducers.csv, PAWedges.csv) ─────────

BEAMTOOL_PREFERRED = ('Evident', 'Olympus')   # newer Evident rows win over Olympus rows of the same part
FACE_SHAPES = {'flat': 'Flat', 'aod': 'AOD', 'aid': 'AID', 'cod': 'COD', 'cid': 'CID', 'sod': 'SOD'}


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _dedupe(rows):
    """One row per part number, preferring Evident over Olympus; other makers keep their own."""
    chosen = {}
    for row in rows:
        part = (row.get('PartNo') or '').strip()
        if not part:
            continue
        maker = (row.get('Manufacturer') or '').strip()
        current = chosen.get(part)
        rank = BEAMTOOL_PREFERRED.index(maker) if maker in BEAMTOOL_PREFERRED else len(BEAMTOOL_PREFERRED)
        if current is None or rank < current[0]:
            chosen[part] = (rank, row)
    return [row for _, row in chosen.values()]


def _probe_series(part):
    """'A1' for 10L32-A1, 'PWZ3' for 5L32-PWZ3; '' when the part number has no series suffix."""
    match = re.search(r'-([A-Z]{1,4}\d{1,3})$', part)
    return match.group(1) if match else ''


def _wedge_series(maker, part):
    """'A10' for SA10-N55S / SA10C-…, 'PWZ1' for SPWZ1-…; only Evident / Olympus name wedges this way."""
    if maker not in BEAMTOOL_PREFERRED:
        return ''
    match = re.match(r'S([A-Z]+\d+)', part)
    return match.group(1) if match else ''


def _wedge_angle_and_wave(part):
    """Nominal refracted angle and wave type from names like SA1-N60S, SA2-0L, AS - 55SW."""
    base = part.split(' ', 1)[0] if ' - ' not in part else part
    match = re.search(r'(?:^|-|\s)[A-Z]{0,2}(\d{1,2})(SW|LW|S|L)\b', base)
    if not match:
        return None, ''
    return float(match.group(1)), 'SW' if match.group(2).startswith('S') else 'LW'


def _probe_fit(part):
    """The probe text after the wedge name: 'SA1-N60S 10L32' -> '10L32', 'ABWX1249_10L32-A1' -> '10L32-A1'."""
    if ' - ' in part:
        return ''
    for separator in (' ', '_'):
        if separator in part:
            return part.split(separator, 1)[1].strip()
    return ''


def _beamtool_probe(row):
    part = row['PartNo'].strip()
    values = {
        'model': part,
        'manufacturer': (row.get('Manufacturer') or '').strip(),
        'series': _probe_series(part),
        'frequency': _number(row.get('Frequency')),
        'elements': int(_number(row.get('TotalElements'))) if _number(row.get('TotalElements')) else None,
        'pitch': _number(row.get('ElementPitch')),
        'elevation': _number(row.get('ElementPassiveWidth')),
        'source': BEAMTOOL_SOURCE,
    }
    return {k: v for k, v in values.items() if v not in (None, '')}


def _beamtool_wedge(row):
    part = row['PartNo'].strip()
    maker = (row.get('Manufacturer') or '').strip()
    refracted, wave = _wedge_angle_and_wave(part)
    x = _number(row.get('X'))
    shape = next((FACE_SHAPES[v.strip().lower()] for v in (row.get('BottomFaceShape'), row.get('WedgeType'))
                  if (v or '').strip().lower() in FACE_SHAPES), '')
    diameter = _number(row.get('PartDiameter'))
    fit = _probe_fit(part)
    fit_series = re.search(r'-([A-Z]{1,4}\d{1,3})\b', fit)  # '10L32-A1' names the probe's series too
    values = {
        'model': part,
        'manufacturer': maker,
        'probe_series': _wedge_series(maker, part) or (fit_series.group(1) if fit_series else ''),
        'probe_fit': fit,
        'refracted_angle': refracted,
        'wave_type': wave,
        'wedge_angle': _number(row.get('Angle')),
        'velocity': _number(row.get('Velocity')),
        'height': _number(row.get('Height')),
        'length': _number(row.get('Length')),
        'width': _number(row.get('W')),
        # Beamtool's X is the wedge front to the first element; the catalogue stores it as OmniScan
        # does, negative behind the front face. Z is the first element's height.
        'primary_offset': -x if x is not None else None,
        'first_element_height': _number(row.get('Z')),
        'secondary_offset': _number(row.get('Y')),
        'roof_angle': _number(row.get('RoofAngle')) or None,
        'bottom_face': shape,
        'part_diameter': diameter if diameter and diameter > 0 else None,
        'source': BEAMTOOL_SOURCE,
    }
    return {k: v for k, v in values.items() if v not in (None, '')}


def read_beamtool_csv(uploaded):
    """Probes from PATransducers.csv or wedges from PAWedges.csv (told apart by their columns)."""
    try:
        text = uploaded.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        uploaded.seek(0)
        text = uploaded.read().decode('cp1252')
    reader = csv.DictReader(io.StringIO(text, newline=''))
    columns = set(reader.fieldnames or [])
    rows = _dedupe(reader)
    if {'PartNo', 'ElementPitch', 'TotalElements'} <= columns:
        return [_beamtool_probe(r) for r in rows], []
    if {'PartNo', 'Angle', 'X', 'Xt', 'Z'} <= columns:
        return [], [_beamtool_wedge(r) for r in rows]
    raise CatalogueImportError(
        f'"{uploaded.name}" is not a Beamtool probe or wedge library (PATransducers.csv / PAWedges.csv).')


READERS = {
    '.nde': read_nde_catalogue,
    '.csv': read_beamtool_csv,
}


def read_catalogue_file(uploaded):
    """(probes, wedges) from any supported file; raises CatalogueImportError for unsupported or bad files."""
    name = (uploaded.name or '').lower()
    for extension, reader in READERS.items():
        if name.endswith(extension):
            return reader(uploaded)
    supported = ', '.join(sorted(READERS))
    raise CatalogueImportError(f'"{uploaded.name}" is not a supported file. Supported: {supported}.')


# ── Saving ───────────────────────────────────────────────────────────────

KEEP_ON_UPDATE = ('source', 'manufacturer')   # an existing entry keeps where it came from


def _apply(model_class, rows):
    """Creates or updates catalogue entries by model; returns (added, updated, unchanged) model names."""
    existing = {item.model: item for item in model_class.objects.filter(model__in=[r['model'] for r in rows])}
    new, changed_items, added, updated, unchanged = [], {}, [], [], []
    for row in rows:
        row = dict(row)
        name = row.pop('model')
        item = existing.get(name)
        if item is None:
            if name not in added:
                new.append(model_class(model=name, **row))
                added.append(name)
            continue
        changed = [f for f, v in row.items() if f not in KEEP_ON_UPDATE and getattr(item, f) != v]
        for field in changed:
            setattr(item, field, row[field])
        if changed:
            changed_items[name] = (item, changed)
            updated.append(name)
        else:
            unchanged.append(name)
    model_class.objects.bulk_create(new, batch_size=500)
    fields = sorted({f for _, changed in changed_items.values() for f in changed})
    if fields:
        model_class.objects.bulk_update([item for item, _ in changed_items.values()], fields, batch_size=500)
    return added, updated, unchanged


def apply_catalogue(probes, wedges):
    """Saves imported probes and wedges; returns a one-line summary for the user."""
    with transaction.atomic():
        results = {'probe': _apply(ProbeModel, probes), 'wedge': _apply(WedgeModel, wedges)}
    parts = []
    for noun, (added, updated, unchanged) in results.items():
        for verb, names in (('added', added), ('updated', updated), ('already up to date', unchanged)):
            if not names:
                continue
            shown = ', '.join(names[:5]) + (f' and {len(names) - 5} more' if len(names) > 5 else '')
            parts.append(f'{len(names)} {noun} model{"s" if len(names) != 1 else ""} {verb} ({shown})')
    return '; '.join(parts)
