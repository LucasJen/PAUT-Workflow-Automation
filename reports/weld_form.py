"""
The weld form's (100-UTFORM-010) equipment grid: which field goes in which row of the Report
sheet, for the testing instrument (column C), the probe columns (F-I) and the group columns
(L, N, P, Q, S), and which rows don't apply to a probe kind. The editor's grid and the Excel
output both read these, so the two always line up.
"""

PAUT, CONV_LONG, CONV_SHEAR = 'paut', 'conv_long', 'conv_shear'
KIND_CHOICES = [(PAUT, 'PAUT'), (CONV_LONG, '0° L-wave (conventional)'), (CONV_SHEAR, 'SW conventional')]

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
}
GROUP_NA = {
    PAUT: set(),
    CONV_SHEAR: {'angle_increment', 'vpa', 'focal_plane', 'focal_distance'},
    CONV_LONG: {'angle_increment', 'vpa', 'focal_plane', 'focal_distance'},
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
    }
