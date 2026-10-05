"""
The part and weld of a scan plan: units, beam angles, the single-V weld outline, the index offset
and the part's surfaces for the tracer.

All geometry is in inches with the weld centre line at x = 0, the scanning surface at y = 0
and depth increasing downwards. The probe sits on the -x side; side 2 is the mirror image.
"""
import math
import re
from dataclasses import dataclass
from types import SimpleNamespace

from django.core.exceptions import ObjectDoesNotExist

MM_PER_IN = 25.4
M_PER_S_TO_IN_PER_US = 1 / 25400
STEEL_SHEAR = 0.1276                  # in/µs
STEEL_LONGITUDINAL = 0.2320
REXOLITE_VELOCITY = 2330.0            # m/s, typical wedge material when the catalogue has none

# Stand-ins when only one of probe / wedge is picked (mm): an A1 probe on an SA1 wedge
GENERIC_PROBE = SimpleNamespace(pitch=0.6, elements=16, length=17.0, height=25.0)
GENERIC_WEDGE = SimpleNamespace(length=30.0, height=16.0, velocity=None, wedge_angle=None, refracted_angle=None,
                                first_element_height=None, primary_offset=None, wave_type='SW')

PLATE_EXTENT = 1000.0                 # a flat plate's surfaces run this far each way, in


def fmt_in(value):
    return f'{value:.3f}"'


def fmt_length(plan, inches):
    """A length for the drawing in the plan's units."""
    if getattr(plan, 'units', 'imperial') == 'metric':
        return f'{inches * MM_PER_IN:.2f} mm'
    return fmt_in(inches)


def first_number(text):
    match = re.search(r'-?\d+(?:\.\d+)?', text or '')
    return float(match.group()) if match else None


def related(plan, name):
    """A plan's probe_model / wedge_model, or None (also for unsaved plans built from a form)."""
    try:
        return getattr(plan, name, None)
    except ObjectDoesNotExist:
        return None


def part_velocity(plan, wedge):
    """Part velocity in in/µs for the wedge's wave type (L-wave wedges refract a longitudinal beam)."""
    if wedge is not None and wedge.wave_type == 'LW':
        block = related(plan, 'sensitivity_block')
        return first_number(block.velocity_long if block else '') or STEEL_LONGITUDINAL
    return plan.shear_velocity or STEEL_SHEAR


def angles(plan):
    """Beam angles from start to stop (inclusive) in steps of angle_step."""
    start, stop = sorted((plan.angle_start, plan.angle_stop))
    step = max(plan.angle_step or 1.0, 0.1)
    count = int(math.floor((stop - start) / step + 1e-9))
    return [start + i * step for i in range(count + 1)] + ([stop] if (stop - start) % step > 1e-6 else [])


def weld_outline(plan):
    """Fusion faces of the single-V weld, from the cap edge down to the root, for the -x side."""
    t = plan.thickness
    half_gap = (plan.root_gap or 0) / 2
    land = min(plan.root_face or 0, t)
    half_cap_prep = half_gap + (t - land) * math.tan(math.radians(plan.bevel_angle))
    return [(-half_cap_prep, 0.0), (-half_gap, t - land), (-half_gap, t)]


def cap_width(plan):
    """Cap width as entered, or the bevel opening plus 1/16" overlap on each side."""
    if plan.cap_width:
        return plan.cap_width
    return -2 * weld_outline(plan)[0][0] + 0.125


def index_offset(plan):
    """Wedge front to the weld centre line: as entered, else the weld toe (half the cap width)."""
    return plan.index_offset if plan.index_offset is not None else cap_width(plan) / 2


def exit_x(plan):
    """Beam exit (index) point: behind the wedge front by the exit point distance."""
    return -(index_offset(plan) + plan.exit_point)


@dataclass
class Surface:
    """A straight piece of the part's boundary that beams reflect off."""
    a: tuple
    b: tuple
    name: str


@dataclass
class Part:
    """The part's cross-section as the boundary surfaces the tracer reflects beams off."""
    surfaces: list
    thickness: float


def part(plan):
    """A flat plate of the plan's thickness: the scanning surface (OD) and the back wall (ID)."""
    t = plan.thickness
    return Part([Surface((-PLATE_EXTENT, 0.0), (PLATE_EXTENT, 0.0), 'scanning surface'),
                 Surface((-PLATE_EXTENT, t), (PLATE_EXTENT, t), 'back wall')], t)
