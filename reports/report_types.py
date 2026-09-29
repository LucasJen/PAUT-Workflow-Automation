"""
Report types.

Each report type picks the Word template used by "Generate", which editor sections and
fields are shown, and the results-table columns. Values in hidden fields are kept, just not
displayed, so switching type never loses data.

To add a type, append a ReportType to _TYPES:
  - template:        a .docx file in word_templates/
  - sections:        which of SECTIONS the editor shows (defaults to all)
  - hidden_fields:   Report or Setup field names to hide within the shown sections
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
        'project_type', 'procedure', 'report_date', 'test_date',
    )),
    ('technician', 'Technicians', (
        'technician_name', 'certification', 'assistant_name', 'assistant_certification',
    )),
    ('summary', 'Executive summary', ('examination_scope', 'executive_summary')),
    ('scope', 'Scope, references & method', (
        'equipment_id', 'ut_method', 'x_axis_reference', 'y_axis_reference',
        'equipment_overview', 'work_scope',
    )),
    ('drawings', 'Equipment drawings', None),
    ('setups', 'UT setups', None),
    ('results', 'Results table', None),
    ('images', 'Photo summary', None),
)

SECTIONS = tuple(key for key, _, _ in REPORT_SECTIONS)

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


@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    template: str
    sections: tuple = SECTIONS
    hidden_fields: frozenset = frozenset()
    results_columns: tuple = ()

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
    ReportType('paut_long', 'PAUT long form (HIC)', 'paut_hic_long_form.docx',
               results_columns=HIC_RESULTS_COLUMNS),
]

REPORT_TYPES = {t.key: t for t in _TYPES}
DEFAULT_REPORT_TYPE = 'paut_long'


def get_report_type(key):
    """Returns the ReportType for `key`, falling back to the default for unknown keys."""
    return REPORT_TYPES.get(key) or REPORT_TYPES[DEFAULT_REPORT_TYPE]


def report_type_choices():
    return [(t.key, t.label) for t in _TYPES]
