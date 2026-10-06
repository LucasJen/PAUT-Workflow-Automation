"""
Report types.

Each report type picks the Word template used by "Generate", which editor sections and
fields are shown, and the results-table columns. Values in hidden fields are kept, just not
displayed, so switching type never loses data.

To add a type, append a ReportType to _TYPES:
  - template:        a .docx file in word_templates/ (default: the master template, whose
                     section blocks print only for the sections this type lists), or an
                     .xlsx file in excel_templates/ when output_format is 'xlsx'
  - output_format:   'docx' (Word report) or 'xlsx' (Excel form, filled through Excel)
  - sections:        which of SECTIONS the editor shows (defaults to all)
  - hidden_fields:   Report or Setup field names to hide within the shown sections, or one of
                     EDITOR_PARTS (parts of the editor that aren't model fields)
  - results_columns: (key, heading) pairs for the results table; the template uses the keys
                     (r.scan_id, r.comments, ...). The first column is the Scan ID and the
                     'comments' column feeds the photo summary. Empty = free-form columns.
No migration is needed; Report.report_type stores the key.
"""
from dataclasses import dataclass

# Editor sections in display order: (key, title, Report fields or None for special sections)
REPORT_SECTIONS = (
    ('project', 'Project information', (
        'document_title', 'client', 'location', 'work_order', 'project_number',
        'project_type', 'procedure', 'procedure_rev', 'report_date', 'test_date', 'test_end_date',
        'address', 'contractor', 'item_description', 'exam_code', 'acceptance_standard',
    )),
    ('personnel', 'Personnel', None),
    ('summary', 'Executive summary', ('examination_scope', 'executive_summary')),
    ('scope', 'Scope, references & method', (
        'asset_description', 'equipment_id', 'ut_method', 'x_axis_reference', 'y_axis_reference',
        'equipment_overview', 'work_scope',
    )),
    ('discussion', 'Discussion', ('discussion',)),
    ('drawings', 'Equipment drawings', None),
    ('setups', 'UT setups', None),
    ('equipment', 'Equipment & parameters', None),
    ('materials', 'Sensitivity block & test material', None),
    ('results', 'Results table', None),
    ('weld_cal', 'Calibration, scan plan & notes', (
        'cal_time_initial', 'cal_time_check1', 'cal_time_check2', 'cal_time_out', 'scan_plan',
    )),
    # The weld form's results: welds with their indications (weld_results.js), saved as results rows
    ('weld_results', 'Results', None),
    # The weld form has two signature lines: a technician and a reviewer, no list of people (last, as on
    # the form)
    ('weld_personnel', 'Personnel', ('weld_technician', 'weld_technician_cert', 'weld_reviewer', 'weld_reviewer_cert')),
    ('images', 'Photo summary', None),
)

SECTIONS = tuple(key for key, _, _ in REPORT_SECTIONS)

# Report fields a special section shows below its own content (editor/<key>.html renders them);
# Preferences › Defaults lists them under that section's title
SECTION_FIELDS = {
    'weld_results': ('notes',),   # the weld form's Notes box sits under its results
}

# Field sections laid out in two columns (pairs: a name and its certification) instead of three
TWO_COLUMN_SECTIONS = frozenset({'weld_personnel'})

# Parts of the editor a report type can hide like a field (data-field in the templates)
EDITOR_PARTS = frozenset({'cal_images'})   # a setup's calibration screenshots

# Fields only the Excel weld form uses
WELD_ONLY_FIELDS = frozenset({
    'address', 'contractor', 'item_description', 'exam_code', 'acceptance_standard', 'procedure_rev', 'scan_plan',
})

# Fields only the corrosion form (598-PAUTFORM-009) uses
CORROSION_ONLY_FIELDS = frozenset({'inspection_material', 'inspection_temp', 'description'})

# A setup on the corrosion form's Setup Information page: everything else is hidden there
CORROSION_SETUP_FIELDS = frozenset({
    'title', 'surface_prep', 'material_temp', 'tr_min', 'tr_max', 'inspection_material', 'inspection_temp',
    'scope_model', 'scope_serial', 'cal_material', 'cal_block_type', 'cal_block_serial', 'transducer_model',
    'transducer_serial',
})
SETUP_FORM_FIELDS = frozenset({
    'title', 'procedure', 'units', 'manufacturer', 'scope_platform', 'scope_model', 'scope_serial',
    'transducer_model', 'transducer_serial', 'probe_diameter', 'wedge_model', 'wedge_angle', 'foc_depth',
    'wave_propagation', 'freq', 'elements', 'x_res', 'y_res', 'scan_length', 'scan_width', 'angle_step',
    'angle_range', 'sound_velocity', 'gain', 'beam_gain', 'ref_gain', 'voltage', 'beam_formation', 'active_elements',
    'element_aperture', 'element_step', 'pcs', 'scan_pattern', 'encoder_resolution', 'digitizing_frequency',
    'pulse_width', 'band_pass_filter', 'calibrations', 'gates', 'specimen_od', 'specimen_thickness',
    'specimen_dimensions', 'inspection_material', 'inspection_temp', 'cal_material', 'material_temp',
    'cal_block_type', 'cal_block_serial', 'surface_prep', 'tr_min', 'tr_max', 'couplant', 'exam_surface',
    'scope_cal_due', 'module_model', 'module_serial', 'module_cal_due', 'software_version', 'scanner_type',
    'scanner_model', 'analysis_software', 'analysis_software_version', 'scan_speed', 'cable_type', 'cable_length',
    'wedge_material', 'wedge_curve', 'focal_plane', 'time_base', 'points_quantity', 'smoothing',
    'amplitude_range', 'transfer_db', 'scanning_db', 'source_file', 'acquisition_date', 'catalogue_probe',
    'catalogue_wedge', 'first_element', 'aperture_elements', 'index_offset', 'wedge_primary_offset',
    'wedge_first_element_height', 'wedge_velocity', 'wedge_length', 'wedge_height', 'weld_bevel_angle',
    'weld_root_face', 'weld_root_gap', 'weld_cap_width',
})

# The methods the corrosion form's Formulas sheet describes (its Setup Information page looks
# the description up by this name)
CORROSION_METHODS = ('PAUT Angle Beam', 'HydroFORM', 'UT Shear Wave', 'AUT', 'Manual UT', 'TOFD', 'PCI', 'FMC / TFM')

MASTER_TEMPLATE = 'paut_master.docx'

# Results columns of the HIC reference report (2026-08-PAUT-HIC_LVLA-15V3)
HIC_RESULTS_COLUMNS = (
    ('scan_id', 'Scan ID'),
    ('orientation', 'Scan Orient.'),
    ('x_range', 'X Axis (Circ.) Start/Stop (In.)'),
    ('y_range', 'Y Axis (Axial) Start/Stop (In.)'),
    ('avg_thk', 'Average Thk (in.)'),
    ('min_thk', 'Min. Thk (in.)'),
    ('comments', 'Results'),
)

# Results columns of the weld form (100-UTFORM-010). One row per flaw: a row with a blank
# Weld ID is another flaw on the weld above it; a row with a flaw Type gets an indication page.
WELD_RESULTS_COLUMNS = (
    ('weld_id', 'Weld ID'),
    ('welder_id', 'Welder ID'),
    ('cl_offset', 'C/L Offset (in)'),
    ('weld_width', 'Weld Width (in)'),
    ('scan_start', 'Scan Start'),
    ('scan_direction', 'Scan Direction'),
    ('probe1_location', 'Probe 1 Location'),
    ('probe1_thk', 'Probe 1 Thickness'),
    ('probe2_thk', 'Probe 2 Thickness'),
    ('circ_start', 'Circ Start (in)'),
    ('length', 'Length (in)'),
    ('axial_pos', 'Axial Pos. (in)'),
    ('depth', 'Depth (in)'),
    ('height', 'Height (in)'),
    ('amp', '% Amp'),
    ('flaw_type', 'Type'),
    ('accept', 'Accept / Reject'),
    ('comments', 'Notes / Comments'),
)


@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    template: str = MASTER_TEMPLATE
    sections: tuple = SECTIONS
    hidden_fields: frozenset = frozenset()
    results_columns: tuple = ()
    output_format: str = 'docx'
    # The editor outlines empty fields by where their value comes from (reports/fill_marks.py)
    fill_marks: bool = False
    # Guided Creation can build it from a job's files (reports/views/start.py)
    guided: bool = False
    # (key, text) pairs the editor shows for this type instead of the usual wording: a field's
    # label (its name), a section's title ('section:<key>') or any [data-label="<key>"] text
    labels: tuple = ()
    # (field, section) pairs: a field shown in another section than its usual one for this type
    field_homes: tuple = ()
    # Guided editor: the steps done before it opened, where to go when there's no equipment yet,
    # and the step before the preview
    wizard_done: tuple = ('Files', 'Welds')
    wizard_equipment_step: str = 'equipment'
    wizard_last_step: str = 'scanplan'

    @property
    def results_headings(self):
        return [heading for _, heading in self.results_columns]

    def as_json(self):
        return {
            'label': self.label,
            'sections': list(self.sections),
            'hidden_fields': sorted(self.hidden_fields),
            'results_columns': [{'key': key, 'heading': heading} for key, heading in self.results_columns],
            'fill_marks': self.fill_marks,
            'labels': dict(self.labels),
            'field_homes': dict(self.field_homes),
        }


_TYPES = [
    ReportType(
        'paut_long', 'PAUT long form (HIC)',
        sections=tuple(s for s in SECTIONS
                       if s not in ('weld_cal', 'equipment', 'materials', 'weld_results', 'weld_personnel')),
        hidden_fields=WELD_ONLY_FIELDS | CORROSION_ONLY_FIELDS,
        results_columns=HIC_RESULTS_COLUMNS,
        fill_marks=True,
    ),
    ReportType(
        'paut_weld', 'PAUT weld (Excel)',
        template='paut_weld.xlsx', output_format='xlsx',
        # The photo summary and calibration screenshots are left to the workbook
        sections=('project', 'equipment', 'materials', 'weld_cal', 'weld_results', 'weld_personnel'),
        hidden_fields=frozenset({'document_title', 'project_number', 'project_type', 'test_date', 'test_end_date',
                                 'cal_images'}),
        results_columns=WELD_RESULTS_COLUMNS,
        fill_marks=True,
        guided=True,
    ),
    ReportType(
        'paut_corrosion', 'PAUT corrosion (Excel)',
        template='paut_corrosion.xlsx', output_format='xlsx',
        # Form 598-PAUTFORM-009: Summary, a Setup Information page per setup, drawings, images
        sections=('project', 'summary', 'setups', 'drawings', 'images', 'weld_personnel'),
        hidden_fields=frozenset({
            'document_title', 'project_number', 'project_type', 'test_end_date', 'address', 'contractor',
            'exam_code', 'acceptance_standard', 'scan_id',
        }) | (SETUP_FORM_FIELDS - CORROSION_SETUP_FIELDS),
        labels=(
            ('item_description', 'Title: Examinations on Selected Areas On…'),
            ('equipment_id', 'Unit / equipment'),
            ('executive_summary', 'Summary of results'),
            ('notes', 'Notes'),
            ('title', 'Method'),
            ('material_temp', 'Calibration temperature'),
            ('cal_material', 'Cal. block material'),
            ('tr_min', 'Thickness range from'),
            ('tr_max', 'Thickness range to'),
            ('caption', 'Caption'),
            ('image', 'Image'),
            ('cal_images', 'Setup image (the first one is printed on the setup page)'),
            ('section:summary', 'Examination scope, results & notes'),
            ('section:setups', 'Setup information'),
            ('section:drawings', 'Drawings'),
            ('section:images', 'Images'),
            ('section:weld_personnel', 'Personnel'),
            ('drawings_intro', 'Each drawing gets its own page: landscape pictures on the Horizontal Drawing '
                               'page, portrait ones on the Vertical Drawing page.'),
            ('images_intro', 'Two images per page, each with a caption and a description.'),
            ('image_kind', 'Image'),
        ),
        field_homes=(('equipment_id', 'project'), ('notes', 'summary')),
        guided=True,
        wizard_done=('Files', 'Pictures'),
        wizard_equipment_step='setups',
        wizard_last_step='images',
    ),
]

REPORT_TYPES = {t.key: t for t in _TYPES}
DEFAULT_REPORT_TYPE = 'paut_long'


def get_report_type(key):
    """Returns the ReportType for `key`, falling back to the default for unknown keys."""
    return REPORT_TYPES.get(key) or REPORT_TYPES[DEFAULT_REPORT_TYPE]


def report_type_choices():
    return [(t.key, t.label) for t in _TYPES]


def guided_report_types():
    """Every report type for Guided Creation's picker, those it can build first: [(ReportType, guided)]."""
    return sorted(((t, t.guided) for t in _TYPES), key=lambda pair: not pair[1])
