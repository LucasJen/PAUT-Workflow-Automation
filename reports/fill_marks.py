"""
Fill marks: the report editor outlines empty fields by where their value comes from
(static/reports/js/fill_marks.js), on report types with fill_marks (report_types.py).

'auto' (yellow): an .nde import, the scope library or the sensitivity block usually fills it.
'user' (red): only the technician can. Fields in neither list aren't marked (optional ones,
or ones only some techniques have). A field a report type hides isn't marked on it, so one list
serves both the weld form and the long form.
"""
from . import weld_form

# The weld form's probe and group columns
PROBE_AUTO_FIELDS = {'make', 'model', 'frequency', 'wedge_model', 'wedge_angle', 'wedge_diameter'}
PROBE_USER_FIELDS = {'label', 'serial', 'cable_type', 'cable_length', 'wedge_material', 'wedge_curve', 'probe_check'}
GROUP_AUTO_FIELDS = {'scan', 'wave_mode', 'angles', 'elements', 'angle_increment', 'vpa', 'focal_distance',
                     'time_base', 'voltage', 'points_quantity', 'filter', 'reference_db'}
GROUP_USER_FIELDS = {'focal_plane', 'smoothing', 'amplitude_range', 'transfer_db', 'scanning_db'}

# Report fields: the weld form's instrument and material card, and both forms' typed fields
REPORT_AUTO_FIELDS = ({name for name, _, _ in weld_form.INSTRUMENT_ROWS} | {name for name, _ in weld_form.material_fields()}
                      | {'sensitivity_block'})
REPORT_USER_FIELDS = {
    # Project (both forms)
    'client', 'location', 'work_order', 'procedure', 'report_date',
    # Weld form
    'procedure_rev', 'address', 'contractor', 'item_description', 'exam_code', 'acceptance_standard',
    'cal_time_initial', 'cal_time_check1', 'cal_time_check2', 'cal_time_out', 'notes',
    'weld_technician', 'weld_technician_cert', 'weld_reviewer', 'weld_reviewer_cert',
    # Long form (the end date, UT method and Discussion are optional: blank has a meaning)
    'document_title', 'project_number', 'project_type', 'test_date',
    'examination_scope', 'executive_summary',
    'asset_description', 'equipment_id', 'x_axis_reference', 'y_axis_reference', 'equipment_overview', 'work_scope',
}

# The long form's UT setup blocks: what the .nde (and scope library) gives, and what's typed.
# Values only some techniques have (PCS, element step, beam gain...) aren't marked.
SETUP_AUTO_FIELDS = {
    'manufacturer', 'scope_platform', 'scope_model', 'scope_serial', 'transducer_model',
    'wedge_model', 'wedge_angle', 'wave_propagation', 'freq', 'elements', 'x_res', 'angle_range',
    'sound_velocity', 'gain', 'voltage', 'beam_formation', 'active_elements', 'band_pass_filter',
    'specimen_od', 'specimen_thickness', 'tr_min', 'tr_max', 'source_file', 'acquisition_date',
}
SETUP_USER_FIELDS = {
    'title', 'transducer_serial', 'cal_block_type', 'cal_block_serial', 'surface_prep', 'material_temp',
    'couplant', 'exam_surface',
    # The Short Form's setup page
    'method_description',
}

# The long form's people
PERSON_USER_FIELDS = {'name'}

# Scan plans: what Fill from setup / the sensitivity block usually gives (yellow); every field the
# drawing can't be made without, and the name, is red (mark_scan_plan)
SCAN_PLAN_AUTO_FIELDS = {'sensitivity_block', 'pipe_size', 'thickness', 'probe_model', 'wedge_model',
                         'outside_diameter'}


def mark_scan_plan(form):
    """A scan plan form's fill marks: the required fields (and the name) red, SCAN_PLAN_AUTO_FIELDS yellow."""
    required = {name for name, field in form.fields.items() if field.required}
    mark_fill(form, SCAN_PLAN_AUTO_FIELDS, required | {'name'})


def mark_fill(form, auto, user):
    """Tags the form's fields data-fill="auto" / "user" for fill_marks.js."""
    for name, field in form.fields.items():
        if name in auto:
            field.widget.attrs['data-fill'] = 'auto'
        elif name in user:
            field.widget.attrs['data-fill'] = 'user'
