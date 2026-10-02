"""
Report defaults (Library › Defaults): per report type, values for its report fields and for new
setup blocks, or on the weld form for its testing instrument and prefilled probe / group columns. A new report opens with them; anything the user types, or that a client, a loaded
setup, an NDE import or a scan plan fills in, replaces them.
"""
from datetime import date

from django.db import models
from django.forms import formset_factory, modelform_factory

from . import weld_form
from .forms import ReportForm, ReportGroupForm, ReportProbeForm, SetupForm
from .models import Report, ReportDefaults, Setup
from .report_types import REPORT_SECTIONS, SECTION_FIELDS, get_report_type

# Report fields that are per job, never defaults
REPORT_EXCLUDED = {'document_filename', 'document_title', 'report_date', 'test_date', 'test_end_date'}

# Setup fields that come from the job's own data (the .nde file), never defaults
SETUP_EXCLUDED = {'source_file', 'acquisition_date', 'index_offset', 'wedge_primary_offset',
                  'wedge_first_element_height', 'wedge_velocity', 'wedge_length', 'wedge_height'}


# Grid column fields that come from the job's own data, never defaults
COLUMN_EXCLUDED = {'DELETE', 'ORDER', 'source_file', 'probe_column'}
INSTRUMENT_FIELDS = [name for name, _, _ in weld_form.INSTRUMENT_ROWS]


def has_setups(report_type):
    return 'setups' in get_report_type(report_type).sections


def has_grid(report_type):
    return 'equipment' in get_report_type(report_type).sections


def report_fields(report_type):
    """The report fields a type's defaults cover: those its editor shows, as (section key, title, names)."""
    rtype = get_report_type(report_type)
    sections = []
    for key, title, names in REPORT_SECTIONS:
        names = names or SECTION_FIELDS.get(key)
        if key not in rtype.sections or not names:
            continue
        names = [n for n in names if n not in REPORT_EXCLUDED and n not in rtype.hidden_fields]
        if names:
            sections.append((key, title, names))
    return sections


def setup_fields():
    return [name for _, names in SetupForm.fieldsets_spec for name in names if name not in SETUP_EXCLUDED]


def report_defaults_form(report_type, *args, **kwargs):
    names = [n for _, _, ns in report_fields(report_type) for n in ns]
    if has_grid(report_type):
        names += INSTRUMENT_FIELDS  # shown in the grid's Testing instrument table
    if 'materials' in get_report_type(report_type).sections:
        names += ['sensitivity_block'] + [name for name, _ in weld_form.material_fields()]   # the materials card
    form = modelform_factory(Report, form=ReportForm, fields=names)(*args, **kwargs)
    form.fields.pop('report_type', None)  # declared on ReportForm; the defaults record is per type
    return form


def setup_defaults_form(*args, **kwargs):
    return modelform_factory(Setup, form=SetupForm, fields=setup_fields())(*args, prefix='setup', **kwargs)


ProbeColumnsFormSet = formset_factory(ReportProbeForm, extra=0, can_delete=True, can_order=True)
GroupColumnsFormSet = formset_factory(ReportGroupForm, extra=0, can_delete=True, can_order=True)


def column_formsets(data=None, probes=(), groups=()):
    """
    (probes, groups) formsets for a defaults set's prefilled columns, laid out by the same grid
    as the report editor (same prefixes); groups choose their probe column by its index.
    """
    probe_formset = ProbeColumnsFormSet(data, initial=list(probes) or None, prefix='probes')
    count = int(data.get('probes-TOTAL_FORMS', 0) or 0) if data is not None else len(probes)
    choices = [(str(i), f'P{i + 1}') for i in range(max(count, weld_form.MAX_PROBES))]
    group_formset = GroupColumnsFormSet(data, initial=list(groups) or None, prefix='groups',
                                        form_kwargs={'probe_choices': choices})
    return probe_formset, group_formset


def in_page_order(formset):
    """A valid column formset's forms in the order weld_grid.js put them on the page (ORDER)."""
    def position(item):
        index, form = item
        order = (form.cleaned_data or {}).get('ORDER')
        return (order is None, order or 0, index)
    return [form for _, form in sorted(enumerate(formset.forms), key=position)]


def columns_from(probe_formset, group_formset):
    """
    (probe columns, group columns) to store from valid column formsets: removed and empty columns
    left out, columns in their order on the page, groups' probe_column renumbered to the probe's
    place among the kept ones.
    """
    def values(form):
        return {k: v for k, v in values_from(form).items() if k not in COLUMN_EXCLUDED}

    probes, place = [], {}
    for form in in_page_order(probe_formset):
        kept = values(form)
        if form in probe_formset.deleted_forms or not set(kept) - {'kind'}:
            continue
        place[form.prefix.rsplit('-', 1)[1]] = str(len(probes))
        probes.append(kept)
    groups = []
    for form in in_page_order(group_formset):
        kept = values(form)
        if form in group_formset.deleted_forms or not kept:
            continue
        column = form.cleaned_data.get('probe_column') or ''
        probe = column if column == weld_form.NOT_USED else place.get(column)
        groups.append({**kept, 'probe_column': probe} if probe is not None else kept)
    return probes, groups


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
    """
    {report type: {'report': {...}, 'setup': {...}, 'probes': [...], 'groups': [...]}} for the report
    editor's type switching and a new report's prefilled grid columns.
    """
    return {d.report_type: {'report': d.report_values, 'setup': d.setup_values,
                            'probes': d.probe_columns, 'groups': d.group_columns}
            for d in ReportDefaults.objects.filter(in_use=True)}
