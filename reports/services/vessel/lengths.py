"""
Lengths as typed on a vessel drawing's inputs, stored in inches: feet-inches as the client
drawings write them (14'-0", 5'-6 1/2", 66", 66) or millimetres (1676, 1676 mm) when the vessel is
metric. A value marked with ' or " is imperial and one marked mm is metric whatever the units.
static/reports/js/vessel.js parses and formats the same way in the browser.
"""
import re
from fractions import Fraction

MM_PER_IN = 25.4
_NUMBER = re.compile(r'^\d*\.?\d+$')
_FRACTION = re.compile(r'^(\d+)/(\d+)$')


def _inches_part(text):
    """'6 1/2', '6-1/2', '1/2', '6.5', '' -> inches."""
    total = 0.0
    for token in re.split(r'[\s-]+', text.strip()):
        if not token:
            continue
        fraction = _FRACTION.match(token)
        if fraction:
            if int(fraction.group(2)) == 0:
                raise ValueError(token)
            total += int(fraction.group(1)) / int(fraction.group(2))
        elif _NUMBER.match(token):
            total += float(token)
        else:
            raise ValueError(token)
    return total


def parse_length(text, metric=False):
    """Inches for a typed length, None for a blank one; ValueError for one that can't be read."""
    t = str(text or '').strip().lower().replace('′', "'").replace('″', '"').replace("''", '"')
    if not t:
        return None
    if t.endswith('mm'):
        return float(t[:-2].strip()) / MM_PER_IN
    if metric and "'" not in t and '"' not in t:
        return float(t) / MM_PER_IN
    t = t.replace('ft', "'").replace('in', '"')
    feet, _, rest = t.rpartition("'")
    feet = feet.strip()
    if feet and not _NUMBER.match(feet):
        raise ValueError(text)
    inches = _inches_part(rest.replace('"', ' ').lstrip(' -'))
    return (float(feet) * 12 if feet else 0.0) + inches


def _inches_text(inches):
    """6.5 -> '6 1/2' (to the nearest 1/16)."""
    whole = int(inches)
    fraction = Fraction(round((inches - whole) * 16), 16)
    if fraction >= 1:
        whole, fraction = whole + 1, fraction - 1
    if not fraction:
        return str(whole)
    return f'{whole} {fraction}' if whole else str(fraction)


def format_length(inches, metric=False, feet_from=36):
    """
    A stored length as it shows in an input: '1676 mm', or feet-inches from `feet_from` inches up
    (14'-0", 5'-6 1/2") and inches below it (30").
    """
    if inches is None:
        return ''
    if metric:
        mm = round(inches * MM_PER_IN, 1)
        return f'{mm:g} mm'
    inches = round(inches * 16) / 16
    if inches >= feet_from:
        feet = int(inches // 12)
        return f"{feet}'-{_inches_text(inches - feet * 12)}\""
    return f'{_inches_text(inches)}"'


def format_diameter(inches, metric=False):
    """Diameters read in inches up to 10 ft (66", as the client sheets write a drum's ID)."""
    return format_length(inches, metric, feet_from=120)
