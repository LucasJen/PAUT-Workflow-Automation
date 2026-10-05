"""
Scan plans: the part and weld (geometry), the wedge and probe placement (probe), beams traced
through the part (tracer), the drawing as a list of shapes (scene) and its PNG (render).

All geometry is in inches with the weld centre line at x = 0, the scanning surface at y = 0
and depth increasing downwards. The probe sits on the -x side; side 2 is the mirror image.
render_png(plan, side) returns PNG bytes for the scan plan page and the Excel report.
"""
from .coverage import Coverage, Suggestion, coverage, inspection_region, suggest_offset  # noqa: F401
from .geometry import (  # noqa: F401
    GENERIC_PROBE, GENERIC_WEDGE, M_PER_S_TO_IN_PER_US, MM_PER_IN, REXOLITE_VELOCITY, STEEL_LONGITUDINAL,
    STEEL_SHEAR, angles, cap_width, exit_x, first_number, fmt_in, fmt_length, index_offset, part, part_velocity,
    weld_outline,
)
from .probe import HEEL_FRACTION, Layout, at_position, catalogue_layout, exact_layout, layout  # noqa: F401
from .render import WIDTH_PX, render_png, render_scene  # noqa: F401
from .scene import Scene, build_scene  # noqa: F401
from .tracer import Trace, beam_path, trace  # noqa: F401
