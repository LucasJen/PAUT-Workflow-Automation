"""
The weld report's Sensitivity block & test material card: what a library sensitivity block (the
Cal Block Table) fills in, and Auto-detect, which picks the block for the part the report's .nde
imports recorded (Report.scan_part) and fills the item inspected from the scan.
"""
import re

from equipment.models import SensitivityBlock

NUMBER = re.compile(r'-?\d+(?:\.\d+)?')
DIAMETER_TOLERANCE = 0.05    # in: a block for this pipe's outside diameter
THICKNESS_TOLERANCE = 0.02   # in: the scan's wall is this block's test thickness


def _number(text):
    match = NUMBER.search(str(text or ''))
    return float(match.group()) if match else None


def block_values(block):
    """{field: value} a sensitivity block fills in: the card, the TCG block and the instrument's encoder."""
    values = {
        'sensitivity_block': block.pk,
        'pipe_size': block.pipe_size,
        'cal_std_serial': block.serial_number,
        'cal_std_block_type': block.block_type,
        'cal_std_material': block.material,
        'cal_std_vel_shear': block.velocity_shear,
        'cal_std_vel_long': block.velocity_long,
        'cal_std_diameter': block.cal_diameter,
        'cal_std_sch_nom': block.cal_sch_nom,
        'cal_std_temp': block.temperature,
        'cal_std_surface': block.surface_cal,
        'cal_std_couplant': block.couplant,
        'cal_std_bevel': 'N/A',
        'item_block_type': 'N/A',
        'item_material': block.material,
        'item_vel_shear': block.velocity_shear,
        'item_vel_long': block.velocity_long,
        'item_diameter': block.test_diameter,
        'item_sch_nom': block.test_sch_nom,
        'item_temp': block.temperature,
        'item_surface': block.surface_test,
        'item_couplant': block.couplant,
        'item_bevel': block.bevel_geometry,
        # TCG on this block: its notches at 1T, 2T and 3T of its thickness
        'tcg_block': block.serial_number,
        'tcg_ref_block': block.serial_number,
        'tcg_reflector': block.block_type,
        'tcg_thickness': block.cal_thickness or block.reflector_depth,
    }
    return {k: v for k, v in values.items() if v not in (None, '')}


def block_encoder(block):
    """The instrument fields the block's row gives (scanner, encoder steps, resolution, speed)."""
    values = {
        'inst_scanner_model': block.encoder,
        'inst_encoder_cal': block.encoder_steps,
        'inst_scan_res': block.scan_res,
        'inst_scan_speed': block.scan_speed,
    }
    return {k: v for k, v in values.items() if v}


def library_blocks():
    """{pk: {'card': {...}, 'encoder': {...}}} for the card's block picker."""
    return {b.pk: {'card': block_values(b), 'encoder': block_encoder(b)} for b in SensitivityBlock.objects.all()}


def detect_block(part):
    """
    The library block for the scanned part: the one whose test diameter is the part's outside
    diameter, and among those the one whose test (else cal.) thickness is closest to the part's
    wall. Returns (block or None, why).
    """
    od, thickness = _number(part.get('od')), _number(part.get('thickness'))
    if od is None and thickness is None:
        return None, 'The imports recorded no part diameter or thickness; import an .nde first.'
    blocks = list(SensitivityBlock.objects.all())
    if od is not None:
        blocks = [b for b in blocks if (d := _number(b.test_diameter)) is not None and abs(d - od) <= DIAMETER_TOLERANCE]
        if not blocks:
            return None, f'No sensitivity block in the library for a {od:.3f}" pipe.'
    if thickness is not None:
        def wall(block):
            value = _number(block.test_thickness) if _number(block.test_thickness) is not None else _number(block.cal_thickness)
            return abs(value - thickness) if value is not None else float('inf')
        blocks.sort(key=wall)
        if wall(blocks[0]) > THICKNESS_TOLERANCE:
            closest = blocks[0]
            return closest, (f'No block matches the {thickness:.3f}" wall exactly; '
                             f'{closest} ({closest.test_thickness or closest.cal_thickness}") is the closest.')
    return blocks[0], ''


def part_values(part, block=None):
    """The item inspected as scanned (the .nde's specimen), over what the block gives for it."""
    od, thickness = _number(part.get('od')), _number(part.get('thickness'))
    shear, longitudinal, bevel = (_number(part.get(k)) for k in ('shear_velocity', 'long_velocity', 'bevel_angle'))
    values = {}
    if od is not None:
        values['item_diameter'] = f'{od:.3f}"'
    if thickness is not None:
        block_wall = _number(block.test_thickness) if block is not None else None
        # The block's 'Sch 40 / 0.280"' when it is this wall, else the scanned wall
        if block is None or block_wall is None or abs(block_wall - thickness) > THICKNESS_TOLERANCE:
            values['item_sch_nom'] = f'{thickness:.3f}"'
    if part.get('material'):
        values['item_material'] = str(part['material'])
    if shear is not None:
        values['item_vel_shear'] = f'{shear:.3f} in/μs'
    if longitudinal is not None:
        values['item_vel_long'] = f'{longitudinal:.3f} in/μs'
    if bevel is not None:
        values['item_bevel'] = f'{bevel:g} °'
    return values
