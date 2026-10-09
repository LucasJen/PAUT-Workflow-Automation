"""
Vessel drawings: a schematic of a drum, tower, exchanger or tank like the client's FHR sheets
(spec, layout, scene), drawn as a PNG (render) for the editors and a report's Drawings page,
with a report's scan coverage marked on it.
"""
from .lengths import MM_PER_IN, format_diameter, format_length, parse_length  # noqa: F401
from .render import render_scene  # noqa: F401
from .scene import build_scene, clean_coverage, vessel_parts  # noqa: F401
from .spec import (  # noqa: F401
    BOOT, BOTTOM, COMPASS, END_HEAD, SHELL, START_HEAD, TOP, VesselSpec, alpha, direction_choices, ends,
    side_names, spec_from,
)


def render_png(spec, coverage=()):
    """PNG bytes of a vessel (a VesselSpec) with coverage marks."""
    return render_scene(build_scene(spec, coverage))


def report_png(report):
    """A report's vessel drawing with its coverage marked, or None when it has no vessel."""
    if report.vessel_id is None:
        return None
    return render_png(spec_from(report.vessel), report.vessel_coverage or [])


def report_caption(report):
    """The drawing's title in the report: the one typed, or the vessel's name."""
    if report.vessel_caption.strip():
        return report.vessel_caption.strip()
    vessel = report.vessel
    return f'{vessel.name} – scan coverage' if report.vessel_coverage else str(vessel.name)
