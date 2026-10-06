"""
The weld form's (100-UTFORM-010) equipment grid: which field goes in which row of the Report
sheet, for the testing instrument (column C), the probe columns (F-I) and the group columns
(L, N, P, Q, S), and which rows don't apply to a probe kind; and the Material Information,
Additional Block(s) and TCG Parameters cells. The editor and the Excel output both read these,
so the two always line up.
"""
import re

PAUT, CONV_LONG, CONV_SHEAR, NOT_USED = 'paut', 'conv_long', 'conv_shear', 'na'
# N/A keeps a column in its place with every cell N/A (e.g. no 270° probe on this job)
KIND_CHOICES = [(PAUT, 'PAUT'), (CONV_LONG, '0° L-wave (conventional)'), (CONV_SHEAR, 'SW conventional'),
                (NOT_USED, 'N/A')]

MAX_PROBES = 4
MAX_GROUPS = 5
PROBE_COLUMNS = 'FGHI'
GROUP_COLUMNS = 'LNPQS'

# (field, label on the form, Report sheet row)
INSTRUMENT_ROWS = [
    ('inst_name', 'Testing instrument', 15),
    ('inst_manufacturer', 'Manufacturer', 16),
    ('inst_model', 'Model', 17),
    ('inst_serial', 'S/N', 18),
    ('inst_cal_due', 'Cal. due date', 19),
    ('inst_module_model', 'Module model', 20),
    ('inst_module_serial', 'Module S/N', 21),
    ('inst_module_cal_due', 'Module cal. due date', 22),
    ('inst_software_version', 'Software version', 23),
    ('inst_scanner_type', 'Scanner type', 24),
    ('inst_scanner_model', 'Scanner make / model', 25),
    ('inst_analysis_software', 'Analysis software', 26),
    ('inst_analysis_software_version', 'Analysis software version', 27),
    ('inst_encoder_cal', 'Encoder cal. (steps/in)', 33),
    ('inst_scan_res', 'Scan res. (in)', 34),
    ('inst_scan_speed', 'Speed (in/sec)', 35),
]

PROBE_ROWS = [
    ('make', 'Make', 16),
    ('model', 'Model', 17),
    ('frequency', 'Frequency', 18),
    ('cable_type', 'Cable / type', 19),
    ('cable_length', 'Cable / length', 20),
    ('serial', 'Probe S/N', 21),
    ('wedge_material', "Wedge mat'l", 22),
    ('wedge_model', 'Wedge model', 23),
    ('wedge_angle', 'Wedge ref. angle', 24),
    ('wedge_diameter', 'Wedge dia.', 25),
    ('wedge_curve', 'Wedge curve type', 26),
    ('probe_check', 'Probe check', 27),
]
# Editor-only rows above the probe rows (not on the sheet: the kind sets row 15's key)
PROBE_HEAD_ROWS = [
    ('kind', 'Kind'),
    ('catalogue_probe', 'Catalogue probe'),
    ('catalogue_wedge', 'Catalogue wedge'),
]
RELEVANT_GROUP_ROWS = (28, 29, 30)   # 'Relevant Group', 'Add Relevant Group' x2: the groups using the probe

GROUP_ROWS = [
    ('scan', 'Scan', 16),
    ('wave_mode', 'Wave mode', 17),
    ('angles', 'Angle(s)', 18),
    ('elements', 'Ele start / stop', 19),
    ('angle_increment', 'Angle increment', 20),
    ('vpa', 'Ele per VPA / VPA index', 21),
    ('focal_plane', 'Focal plane', 22),
    ('focal_distance', 'Focal distance', 23),
    ('time_base', 'Time base, start / stop', 24),
    ('voltage', 'Pulser voltage', 25),
    ('points_quantity', 'Points quantity', 26),
    ('smoothing', 'Smoothing', 27),
    ('filter', 'Filter settings', 28),
    ('amplitude_range', 'Amplitude range', 29),
    ('reference_db', 'Reference dB', 30),
    ('transfer_db', 'Transfer dB', 31),
    ('scanning_db', 'Scanning dB', 32),
]

# Rows that are N/A for a kind (from the reference's Probe Table): conventional probes have no
# focal law; the 0° dual has no wedge either
PROBE_NA = {
    PAUT: set(),
    CONV_SHEAR: set(),
    CONV_LONG: {'wedge_material', 'wedge_model', 'wedge_angle', 'wedge_diameter', 'wedge_curve'},
    NOT_USED: {name for name, _, _ in PROBE_ROWS},
}
GROUP_NA = {
    PAUT: set(),
    CONV_SHEAR: {'angle_increment', 'vpa', 'focal_plane', 'focal_distance'},
    CONV_LONG: {'angle_increment', 'vpa', 'focal_plane', 'focal_distance'},
    NOT_USED: {name for name, _, _ in GROUP_ROWS},   # an N/A group, or one on an N/A probe
}


def weld_grid_rows():
    """Row definitions and limits for the editor's grid template and weld_grid.js."""
    return {
        'instrument': INSTRUMENT_ROWS,
        'probe_head': PROBE_HEAD_ROWS,
        'probe': PROBE_ROWS,
        'group': GROUP_ROWS,
        'max_probes': MAX_PROBES,
        'max_groups': MAX_GROUPS,
        'probe_na': {kind: sorted(rows) for kind, rows in PROBE_NA.items()},
        'group_na': {kind: sorted(rows) for kind, rows in GROUP_NA.items()},
        'material': MATERIAL_ROWS,
        'additional': ADDITIONAL_ROWS,
        'additional_blocks': [prefix for prefix, _ in ADDITIONAL_BLOCKS],
        'tcg': TCG_FIELDS,
        'tcg_multiples': TCG_MULTIPLES,
    }


# ── Material Information, Additional Block(s) and TCG Parameters ─────────────

# (label, Cal. Std. field (column W), Item Inspected field (column Y), Report sheet row)
MATERIAL_ROWS = [
    ('S/N', 'cal_std_serial', None, 14),
    ('Block type', 'cal_std_block_type', 'item_block_type', 16),
    ('Material', 'cal_std_material', 'item_material', 17),
    ('Velocity shear', 'cal_std_vel_shear', 'item_vel_shear', 18),
    ('Velocity L-wave', 'cal_std_vel_long', 'item_vel_long', 19),
    ('Diameter', 'cal_std_diameter', 'item_diameter', 20),
    ('Sch / nom. thk', 'cal_std_sch_nom', 'item_sch_nom', 21),
    ('Temp (°F)', 'cal_std_temp', 'item_temp', 22),
    ('Surface condition', 'cal_std_surface', 'item_surface', 23),
    ('Exam surface (I.D. / O.D.)', 'cal_std_exam_surface', 'item_exam_surface', 24),
    ('Couplant', 'cal_std_couplant', 'item_couplant', 25),
    ('Bevel geometry', 'cal_std_bevel', 'item_bevel', 26),
]
PIPE_SIZE_CELL = 'U15'

# Additional Block(s) (if used): two blocks, columns W and Y; field = <prefix>_<name>
ADDITIONAL_BLOCKS = (('add1', 'W'), ('add2', 'Y'))
ADDITIONAL_ROWS = [
    ('Block type', 'block_type', 28),
    ('Block S/N', 'serial', 29),
    ('Material', 'material', 30),
    ('Velocity shear', 'vel_shear', 31),
    ('Velocity L-wave', 'vel_long', 32),
    ('Diameter', 'diameter', 33),
    ('Sch / nom. thk', 'sch_nom', 34),
    ('Temp (°F)', 'temp', 35),
    ('Surface condition', 'surface', 36),
    ('Exam surface (I.D. / O.D.)', 'exam_surface', 37),
]

# TCG Parameters: three points at 1T, 2T and 3T of the sensitivity block's thickness T
TCG_POINT_COLUMNS = 'LNP'
TCG_MULTIPLES = (1, 2, 3)
TCG_FIELDS = [
    ('tcg_block', 'TCG block used'),       # L34
    ('tcg_ref_block', 'Ref block used'),   # Q34
    ('tcg_reflector', 'Reflector type'),   # L35, N35, P35
    ('tcg_thickness', 'Block thickness (T)'),   # distances L36, N36, P36 = 1T, 2T, 3T
    ('tcg_amplitude', 'Amplitude'),        # L37, N37, P37
]


def material_fields():
    """(Report field, label) of the Sensitivity block & test material card, in card order."""
    fields = [('pipe_size', 'NPS / Sch')]
    for label, cal, item, _ in MATERIAL_ROWS:
        fields.append((cal, f'Cal. Std. {label.lower()}'))
        if item:
            fields.append((item, f'Item inspected {label.lower()}'))
    for prefix, _ in ADDITIONAL_BLOCKS:
        number = prefix[-1]
        fields += [(f'{prefix}_{name}', f'Additional block {number} {label.lower()}') for label, name, _ in ADDITIONAL_ROWS]
    return fields + TCG_FIELDS


def tcg_distances(thickness):
    """'0.280' -> ['0.280', '0.560', '0.840'] (1T, 2T, 3T); [] when T isn't a number."""
    match = re.search(r'-?\d+(?:\.\d+)?', thickness or '')
    if not match:
        return []
    t = float(match.group())
    return [f'{t * k:.3f}' for k in TCG_MULTIPLES]


def wedge_diameter_for(probe_kind, pipe_diameter):
    """A probe's Wedge dia.: the pipe it's on (the item inspected's diameter); None when it has no wedge."""
    return None if 'wedge_diameter' in PROBE_NA.get(probe_kind, set()) else pipe_diameter
