"""
Report types.

Each report type picks the Word template used by "Generate" and which editor sections
and fields are shown. Values in hidden fields are kept, just not displayed, so switching
type never loses data.

To add a type, append a ReportType to _TYPES:
  - template:      a .docx file in word_templates/
  - sections:      which of SECTIONS the editor shows (defaults to all)
  - hidden_fields: Report or Setup field names to hide within the shown sections
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
    ('setups', 'UT setups', None),
    ('images', 'Images', None),
    ('results', 'Results table', None),
)

SECTIONS = tuple(key for key, _, _ in REPORT_SECTIONS)


@dataclass(frozen=True)
class ReportType:
    key: str
    label: str
    template: str
    sections: tuple = SECTIONS
    hidden_fields: frozenset = frozenset()

    def as_json(self):
        return {
            'label': self.label,
            'sections': list(self.sections),
            'hidden_fields': sorted(self.hidden_fields),
        }


_TYPES = [
    ReportType('paut_long', 'PAUT long form (HIC)', 'paut_hic_long_form.docx'),
]

REPORT_TYPES = {t.key: t for t in _TYPES}
DEFAULT_REPORT_TYPE = 'paut_long'


def get_report_type(key):
    """Returns the ReportType for `key`, falling back to the default for unknown keys."""
    return REPORT_TYPES.get(key) or REPORT_TYPES[DEFAULT_REPORT_TYPE]


def report_type_choices():
    return [(t.key, t.label) for t in _TYPES]
