"""
Report defaults (Library › Defaults): per report type, values for its report fields and for new
setup blocks. A new report opens with them; anything the user types, or that a client, a loaded
setup, an NDE import or a scan plan fills in, replaces them.
"""
from datetime import date

from django.db import models
from django.forms import modelform_factory

from .forms import ReportForm, SetupForm
from .models import Report, ReportDefaults, Setup
from .report_types import REPORT_SECTIONS, get_report_type

# Report fields that are per job, never defaults
REPORT_EXCLUDED = {'document_filename', 'document_title', 'report_date', 'test_date', 'test_end_date'}

# Setup fields that come from the job's own data (the .nde file), never defaults
SETUP_EXCLUDED = {'source_file', 'acquisition_date', 'index_offset', 'wedge_primary_offset',
                  'wedge_first_element_height', 'wedge_velocity', 'wedge_length', 'wedge_height'}


def report_fields(report_type):
    """The report fields a type's defaults cover: those its editor shows, by section."""
    rtype = get_report_type(report_type)
    sections = []
    for key, title, names in REPORT_SECTIONS:
        if key not in rtype.sections or not names:
            continue
        names = [n for n in names if n not in REPORT_EXCLUDED and n not in rtype.hidden_fields]
        if names:
            sections.append((title, names))
    return sections


def setup_fields():
    return [name for _, names in SetupForm.fieldsets_spec for name in names if name not in SETUP_EXCLUDED]


def report_defaults_form(report_type, *args, **kwargs):
    names = [n for _, ns in report_fields(report_type) for n in ns]
    form = modelform_factory(Report, form=ReportForm, fields=names)(*args, **kwargs)
    form.fields.pop('report_type', None)  # declared on ReportForm; the defaults record is per type
    return form


def setup_defaults_form(*args, **kwargs):
    return modelform_factory(Setup, form=SetupForm, fields=setup_fields())(*args, prefix='setup', **kwargs)


def _stored(value):
    """A form value as JSON: model instances as their pk, dates as ISO text; blank -> None."""
    if isinstance(value, models.Model):
        return value.pk
    if isinstance(value, date):
        return value.isoformat()
    if value in (None, '', []):
        return None
    return value


def values_from(form):
    """{field: value} for every field the form has a value for."""
    out = {}
    for name in form.fields:
        value = _stored(form.cleaned_data.get(name))
        if value is not None:
            out[name] = value
    return out


def only_defaults(form, setup_values):
    """
    True when a new setup block holds nothing but the setup defaults (or nothing at all): it
    wasn't really filled in, so it isn't saved as a setup.
    """
    for name in form.changed_data:
        value = _stored(form.cleaned_data.get(name))
        default = setup_values.get(name)
        if value != default and not (value is None and default in (None, '')):
            return False
    return True


def defaults_for(report_type):
    """(report values, setup values) of the type's defaults set in use; empty when there is none."""
    record = ReportDefaults.objects.filter(report_type=report_type, in_use=True).first()
    if record is None:
        return {}, {}
    return dict(record.report_values), dict(record.setup_values)


def all_defaults():
    """{report type: {'report': {...}, 'setup': {...}}} for the report editor's type switching."""
    return {d.report_type: {'report': d.report_values, 'setup': d.setup_values}
            for d in ReportDefaults.objects.filter(in_use=True)}
