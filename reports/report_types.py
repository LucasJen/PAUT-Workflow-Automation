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
    ('results', 'Results table', None),
    ('weld_cal', 'Calibration, scan plan & notes', (
        'cal_accept', 'cal_time_initial', 'cal_time_check1', 'cal_time_check2', 'cal_time_out', 'scan_plan', 'notes',
    )),
    ('images', 'Photo summary', None),
)

SECTIONS = tuple(key for key, _, _ in REPORT_SECTIONS)

# Parts of the editor a report type can hide like a field (data-field in the templates)
EDITOR_PARTS = frozenset({'cal_images'})   # a setup's calibration screenshots

# Fields only the Excel weld form uses
WELD_ONLY_FIELDS = frozenset({
    'address', 'contractor', 'item_description', 'exam_code', 'acceptance_standard', 'procedure_rev', 'scan_plan',
})

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

    @property
    def results_headings(self):
        return [heading for _, heading in self.results_columns]

    def as_json(self):
        return {
            'label': self.label,
            'sections': list(self.sections),
            'hidden_fields': sorted(self.hidden_fields),
            'results_columns': [{'key': key, 'heading': heading} for key, heading in self.results_columns],
        }


_TYPES = [
    ReportType(
        'paut_long', 'PAUT long form (HIC)',
        sections=tuple(s for s in SECTIONS if s not in ('weld_cal', 'equipment')),
        hidden_fields=WELD_ONLY_FIELDS,
        results_columns=HIC_RESULTS_COLUMNS,
    ),
    ReportType(
        'paut_weld', 'PAUT weld (Excel)',
        template='paut_weld.xlsx', output_format='xlsx',
        # Results, the photo summary and calibration screenshots are filled in the workbook
        sections=('project', 'personnel', 'equipment', 'weld_cal'),
        hidden_fields=frozenset({'document_title', 'project_number', 'project_type', 'test_date', 'test_end_date',
                                 'cal_images'}),
        results_columns=WELD_RESULTS_COLUMNS,
    ),
]

REPORT_TYPES = {t.key: t for t in _TYPES}
DEFAULT_REPORT_TYPE = 'paut_long'


def get_report_type(key):
    """Returns the ReportType for `key`, falling back to the default for unknown keys."""
    return REPORT_TYPES.get(key) or REPORT_TYPES[DEFAULT_REPORT_TYPE]


def report_type_choices():
    return [(t.key, t.label) for t in _TYPES]
