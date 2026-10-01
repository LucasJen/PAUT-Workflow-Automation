"""
Which wedges fit which probe.

A wedge fits a probe when the manufacturers match (Olympus and Evident are the same family), the
wedge's probe series matches the probe's (SA1 wedges for A1 probes), and, for library wedges
whose geometry is for a particular probe ("SA1-N60S 10L32", "SA10-N55S 5/10L32",
"SA15-N60S-IH 2.25-3-5"), the probe is one of those. Anything a catalogue entry leaves blank
doesn't restrict the match, except that a Beamtool library wedge whose name names neither a
series nor a probe is only offered for probes without a series.
"""
import re

MANUFACTURER_FAMILIES = {'olympus': 'evident'}
BEAMTOOL_SOURCE = 'ES Beamtool library'

PROBE_TOKEN = re.compile(r'^(\d+(?:\.\d+)?)([A-Z]+)(\d+)', re.IGNORECASE)   # 10L32, 7.5CCEV35
FREQUENCIES = re.compile(r'^\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)+$')              # 2.25-3-5


def _family(manufacturer):
    name = (manufacturer or '').strip().lower()
    return MANUFACTURER_FAMILIES.get(name, name)


def probe_token(model):
    """'10L32' for 10L32-A1: frequency, array type and element count."""
    match = PROBE_TOKEN.match(model or '')
    return f'{float(match.group(1)):g}{match.group(2).upper()}{match.group(3)}' if match else ''


def fit_tokens(fit):
    """
    (probe tokens, frequencies) a library wedge's probe text names, e.g.
    '5/10L32' -> ({'5L32', '10L32'}, set()), '10L32R' -> ({'10L32'}, set()),
    '2.25-3-5' -> (set(), {2.25, 3.0, 5.0}). Text that names no probe gives two empty sets.
    """
    tokens, frequencies = set(), set()
    for part in re.split(r'[\s,_]+', (fit or '').strip()):
        if not part:
            continue
        if FREQUENCIES.match(part):
            frequencies.update(float(f) for f in part.split('-'))
            continue
        part = re.sub(r'-[A-Z]+\d+[A-Z]?$', '', part, flags=re.IGNORECASE)  # drop a '-A10' series suffix
        part = re.sub(r'R$', '', part)                                     # reversed mounting
        match = re.match(r'^((?:\d+(?:\.\d+)?/)*\d+(?:\.\d+)?)([A-Z]+)(\d+)$', part, flags=re.IGNORECASE)
        if match:
            for frequency in match.group(1).split('/'):
                tokens.add(f'{float(frequency):g}{match.group(2).upper()}{match.group(3)}')
    return tokens, frequencies


def wedge_fits_probe(wedge, probe):
    if probe is None or wedge is None:
        return True
    if _family(wedge.manufacturer) and _family(probe.manufacturer) \
            and _family(wedge.manufacturer) != _family(probe.manufacturer):
        return False
    if wedge.probe_series and probe.series and wedge.probe_series.lower() != probe.series.lower():
        return False
    tokens, frequencies = fit_tokens(wedge.probe_fit)
    if wedge.source == BEAMTOOL_SOURCE and probe.series and not (wedge.probe_series or tokens or frequencies):
        return False  # a library wedge whose name doesn't say which probe it is for
    if tokens and probe_token(probe.model) not in tokens:
        return False
    if frequencies and probe.frequency is not None and not any(abs(probe.frequency - f) < 0.01 for f in frequencies):
        return False
    return True


def wedges_for_probe(probe, wedges):
    """The wedges (from `wedges`) that fit `probe`: its own series first (SA1 for A1), then by name."""
    series = (probe.series or '').lower()
    fitting = [w for w in wedges if wedge_fits_probe(w, probe)]
    return sorted(fitting, key=lambda w: ((w.probe_series or '').lower() != series, w.model.lower()))
