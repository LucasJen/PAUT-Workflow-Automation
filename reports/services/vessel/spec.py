"""
What a vessel drawing is made from (the Vessel model's values, saved or not), and where its
compass directions land on the side view.

Directions: a vertical vessel or tank is seen from one compass direction (view_from), so the
right-hand side of the drawing faces 90 deg clockwise of the way the viewer looks. A horizontal
vessel or exchanger seen from view_from has its left end 90 deg clockwise of view_from (seen from
the S, the left end is W); its nozzles point Top, Bottom or to one side (the viewer's, or the far
one). Each direction becomes an angle alpha round the axis on the drawing: 0 points to the
drawing's +r side (up on a horizontal vessel, right on a vertical one), 90 at the viewer, 180 to
the -r side and 270 away from the viewer.
"""
from dataclasses import dataclass, field

COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
DEGREES = {name: 45 * i for i, name in enumerate(COMPASS)}
TOP, BOTTOM = 'Top', 'Bottom'
HORIZONTAL_TYPES = ('horizontal', 'exchanger')
VERTICAL_TYPES = ('vertical', 'tank')

# Nozzle locations: on the shell (position along it from the start tangent line), on either head
# (position = offset from the centre line, + to the drawing's +r side) or on a horizontal vessel's
# boot (position down from the shell)
SHELL, START_HEAD, END_HEAD, BOOT = 'shell', 'start', 'end', 'boot'


@dataclass
class VesselSpec:
    vessel_type: str = 'horizontal'
    diameter: float = 60.0                 # inches
    start_head: str = 'ellipsoidal'
    end_head: str = 'ellipsoidal'
    courses: list = field(default_factory=list)   # [{kind, length, diameter, label}] in inches
    nozzles: list = field(default_factory=list)   # [{tag, size, location, position, direction}]
    supports: str = 'auto'
    view_from: str = 'S'
    seam_start: int = 1
    boot_diameter: float = None
    boot_length: float = None
    boot_position: float = None            # inches from the start tangent line to the boot's centre
    name: str = ''
    diameter_basis: str = 'ID'
    metric: bool = False

    @property
    def horizontal(self):
        return self.vessel_type in HORIZONTAL_TYPES

    @property
    def has_boot(self):
        return self.horizontal and bool(self.boot_diameter) and bool(self.boot_length)


def spec_from(vessel):
    """A VesselSpec of a Vessel (saved or a form's unsaved instance)."""
    return VesselSpec(
        vessel_type=vessel.vessel_type, diameter=vessel.diameter, start_head=vessel.start_head,
        end_head=vessel.end_head, courses=list(vessel.courses or []), nozzles=list(vessel.nozzles or []),
        supports=vessel.supports, view_from=vessel.view_from, seam_start=vessel.seam_start or 1,
        boot_diameter=vessel.boot_diameter, boot_length=vessel.boot_length, boot_position=vessel.boot_position,
        name=vessel.name, diameter_basis=vessel.diameter_basis, metric=vessel.units == 'metric',
    )


def facing(spec):
    """The compass degrees the viewer looks towards."""
    return (DEGREES.get(spec.view_from, 180) + 180) % 360


def ends(spec):
    """A horizontal vessel's (left end, right end) compass names; a vertical one's (left, right) sides."""
    look = facing(spec)
    return COMPASS[((look - 90) % 360) // 45], COMPASS[((look + 90) % 360) // 45]


def side_names(spec):
    """A horizontal vessel's (near side, far side) compass names: where the viewer stands, and opposite."""
    look = facing(spec)
    return COMPASS[((look + 180) % 360) // 45], COMPASS[look // 45]


def direction_choices(spec, location=SHELL):
    """The directions a nozzle can take on this vessel at `location`."""
    if location in (START_HEAD, END_HEAD):
        return []                      # a head's nozzles point along the axis
    if spec.horizontal and location == SHELL:
        near, far = side_names(spec)
        return [TOP, near, BOTTOM, far]
    return list(COMPASS) + ([BOTTOM] if location == BOOT else [])


def alpha(spec, direction, location=SHELL):
    """
    The angle round the axis (see the module notes) of a nozzle direction, or None when it can't
    point that way (along a horizontal vessel's axis).
    """
    if spec.horizontal and location == SHELL:
        if direction == TOP:
            return 0.0
        if direction == BOTTOM:
            return 180.0
        if direction not in DEGREES:
            return None
        near, _ = side_names(spec)
        import math
        across = math.cos(math.radians(DEGREES[direction] - DEGREES[near]))
        if abs(across) < 0.3:
            return None
        return 90.0 if across > 0 else 270.0
    if direction not in DEGREES:
        return None
    # Vertical shell, and a horizontal vessel's boot (a short vertical shell): +r is the right
    return float((DEGREES[direction] - facing(spec) - 90) % 360)


def band_alphas(spec, start, stop):
    """
    The angles round the axis a band from one direction to another covers, going clockwise on a
    vertical vessel (seen from above) and Top -> near side -> Bottom -> far side on a horizontal
    one; [0, 360] when either is blank (all the way round).
    """
    if not start or not stop:
        return 0.0, 360.0
    a, b = alpha(spec, start), alpha(spec, stop)
    if a is None or b is None:
        return 0.0, 360.0
    if spec.horizontal:
        b = b if b > a else b + 360
    else:
        b = b if b > a else b + 360
    return a, b
