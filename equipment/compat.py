"""
Which wedges fit which probe.

A wedge fits a probe when the manufacturers match (Olympus and Evident are the same family), the
wedge's probe series matches the probe's (SA1 wedges for A1 probes), and, for library wedges
whose geometry is for particular probes, the probe is one of those. Anything a catalogue entry
leaves blank doesn't restrict the match, except that a Beamtool library wedge whose name names
neither a series nor a probe is only offered for probes without a series.

Beamtool names the probe after the wedge name (wedge.probe_fit). The forms seen in the A1, A2,
A10, A15, A31 and A32 wedges:

    10L32, 10L32R, 10L32-A1        one probe (R = reversed mounting, -A1 = its series)
    5/10L32, 5-10L32, 1-2-5-7-10L16 several frequencies, same array
    2L16, 7CCEV35-16               old frequency shorthand: 1 = 1.5, 2 = 2.25, 3 = 3.5, 7 = 7.5 MHz
    2.25/3/5CCEV35-16, 10CCEV35-32 curved (CCEV) probes: frequencies, radius 35, element count
    L16, L32                       any frequency with that many elements
    2.25-3-5, 7.5-10, 10           frequencies only (A15 wedges)
    dual 5L64, 5L64R Pos2L64       words and the 'Pos…' mounting position after the probe are ignored
"""
import re
from dataclasses import dataclass

MANUFACTURER_FAMILIES = {'olympus': 'evident'}
BEAMTOOL_SOURCE = 'ES Beamtool library'

# Beamtool's short frequency names for the standard Evident frequencies
FREQUENCY_SHORTHAND = {1.0: 1.5, 2.0: 2.25, 3.0: 3.5, 7.0: 7.5}
ELEMENT_COUNTS = {8, 16, 32, 64}     # a lone number after CCEV in these is the element count, not a radius

NUMBER = r'\d+(?:\.\d+)?'
FREQUENCY_LIST = rf'{NUMBER}(?:[/-]{NUMBER})*'
# frequencies, array type, element count / CCEV radius, then an optional '-16' element count
PROBE_TEXT = re.compile(rf'^({FREQUENCY_LIST})?(L|CCEV|DL|DM|M)(\d+)?(?:-(\d+))?$', re.IGNORECASE)
FREQUENCIES_ONLY = re.compile(rf'^{NUMBER}(?:[/-]{NUMBER})*$')


@dataclass(frozen=True)
class ProbeSpec:
    """What a wedge's probe text allows: None means any."""
    frequencies: frozenset = None
    kind: str = None          # 'L' (linear), 'CCEV', ...
    elements: int = None


def _frequency(text):
    value = float(text)
    return FREQUENCY_SHORTHAND.get(value, value)


def _frequencies(text):
    return frozenset(_frequency(f) for f in re.split(r'[/-]', text)) if text else None


def fit_specs(fit):
    """
    The probes a library wedge's probe text names, as ProbeSpecs; empty when the text names
    no probe (e.g. 'GroupA'), so the wedge is matched on its series alone.
    """
    text = re.split(r'\bpos', fit or '', maxsplit=1, flags=re.IGNORECASE)[0]   # drop 'Pos2L64' etc.
    specs = []
    for part in re.split(r'[\s,_]+', text.strip()):
        part = re.sub(r'-[A-Z]+\d+[A-Z]?$', '', part, flags=re.IGNORECASE)     # '-A10', '-A10P'
        part = re.sub(r'R$', '', part)                                          # reversed mounting
        part = re.sub(r'CCEV?-?', 'CCEV', part.rstrip('-'), flags=re.IGNORECASE)  # '5L16-', 'CCEV-35', 'CCE'
        if not part:
            continue
        if FREQUENCIES_ONLY.match(part):
            specs.append(ProbeSpec(frequencies=_frequencies(part)))
            continue
        match = PROBE_TEXT.match(part)
        if not match:
            continue
        frequencies, kind, number, suffix = match.groups()
        kind = kind.upper()
        if kind == 'CCEV':  # CCEV35-16: 35 is the curvature radius, 16 the elements; CCEV16: 16 elements
            if suffix:
                elements = int(suffix)
            else:
                elements = int(number) if number and int(number) in ELEMENT_COUNTS else None
        else:
            elements = int(number) if number else None
        specs.append(ProbeSpec(_frequencies(frequencies), kind, elements))
    return specs


def probe_spec(probe):
    """The frequency, array type and element count of a catalogue probe."""
    match = re.match(r'^(\d+(?:\.\d+)?)(L|CCEV|DL|DM|M)', probe.model or '', re.IGNORECASE)
    kind = match.group(2).upper() if match else None
    frequency = probe.frequency if probe.frequency is not None else (float(match.group(1)) if match else None)
    return frequency, kind, probe.elements


def spec_fits(spec, probe):
    frequency, kind, elements = probe_spec(probe)
    if spec.frequencies is not None and frequency is not None \
            and not any(abs(frequency - f) < 0.01 for f in spec.frequencies):
        return False
    if spec.kind and kind and spec.kind != kind:
        return False
    if spec.elements and elements and spec.elements != elements:
        return False
    return True


def _family(manufacturer):
    name = (manufacturer or '').strip().lower()
    return MANUFACTURER_FAMILIES.get(name, name)


def wedge_fits_probe(wedge, probe):
    if probe is None or wedge is None:
        return True
    if _family(wedge.manufacturer) and _family(probe.manufacturer) \
            and _family(wedge.manufacturer) != _family(probe.manufacturer):
        return False
    if wedge.probe_series and probe.series and wedge.probe_series.lower() != probe.series.lower():
        return False
    specs = fit_specs(wedge.probe_fit)
    if wedge.source == BEAMTOOL_SOURCE and probe.series and not (wedge.probe_series or specs):
        return False  # a library wedge whose name doesn't say which probe it is for
    return not specs or any(spec_fits(spec, probe) for spec in specs)


def wedges_for_probe(probe, wedges):
    """The wedges (from `wedges`) that fit `probe`: its own series first (SA1 for A1), then by name."""
    series = (probe.series or '').lower()
    fitting = [w for w in wedges if wedge_fits_probe(w, probe)]
    return sorted(fitting, key=lambda w: ((w.probe_series or '').lower() != series, w.model.lower()))
