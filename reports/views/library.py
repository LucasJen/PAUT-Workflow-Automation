"""Library › Defaults: named sets of starting values per report type, one in use per type."""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from ..defaults import (
    column_formsets, columns_from, has_grid, has_setups, report_defaults_form, report_fields, setup_defaults_form,
    values_from,
)
from ..materials import library_blocks
from ..weld_form import weld_grid_rows
from ..models import ReportDefaults
from ..report_types import REPORT_SECTIONS, REPORT_TYPES


def defaults_list(request):
    if request.method == 'POST':
        item = get_object_or_404(ReportDefaults, pk=request.POST.get('pk'))
        label = REPORT_TYPES[item.report_type].label if item.report_type in REPORT_TYPES else item.report_type
        if 'use' in request.POST:
            item.use()
            messages.success(request, f'New {label} reports now start from "{item.name}".')
        elif 'duplicate' in request.POST:
            copy = ReportDefaults(name=_free_name(item.report_type, f'{item.name} (copy)'), report_type=item.report_type,
                                  report_values=item.report_values, setup_values=item.setup_values,
                                  probe_columns=item.probe_columns, group_columns=item.group_columns)
            copy.save()
            return redirect('edit-defaults', pk=copy.pk)
        elif 'delete' in request.POST:
            item.delete()
            messages.success(request, f'"{item.name}" deleted.')
        return redirect('defaults-list')
    groups = []
    for key, rtype in REPORT_TYPES.items():
        groups.append({'type': rtype, 'sets': list(ReportDefaults.objects.filter(report_type=key))})
    return render(request, 'reports/defaults_list.html', {'groups': groups})


def _free_name(report_type, name):
    taken = set(ReportDefaults.objects.filter(report_type=report_type).values_list('name', flat=True))
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f'{name} {n}', n + 1
    return candidate


def new_defaults(request, report_type):
    if report_type not in REPORT_TYPES:
        raise Http404
    first = not ReportDefaults.objects.filter(report_type=report_type).exists()
    item = ReportDefaults(report_type=report_type, name=_free_name(report_type, 'Standard' if first else 'New defaults'),
                          in_use=first)
    return _edit(request, item)


def edit_defaults(request, pk):
    return _edit(request, get_object_or_404(ReportDefaults, pk=pk))


def _edit(request, item):
    rtype = REPORT_TYPES.get(item.report_type)
    if rtype is None:
        raise Http404
    errors = []
    # Setup defaults for types with setup blocks; prefilled probe / group columns for the weld
    # form's grid (values for a part the type doesn't show, or that wasn't posted, are kept)
    with_setups, with_grid = has_setups(item.report_type), has_grid(item.report_type)
    data = request.POST if request.method == 'POST' else None
    report_form = report_defaults_form(item.report_type, data, initial=item.report_values)
    setup_form = setup_defaults_form(data, initial=item.setup_values) if with_setups else None
    probes = groups = None
    if with_grid:
        grid_data = data if data is None or 'probes-TOTAL_FORMS' in data else None
        probes, groups = column_formsets(grid_data, item.probe_columns, item.group_columns)
    extra_forms = [f for f in (setup_form, probes, groups) if f is not None]
    if request.method == 'POST':
        name = (request.POST.get('defaults_name') or '').strip()
        if not name:
            errors.append('Give these defaults a name.')
        if not errors and report_form.is_valid() and all(f.is_valid() for f in extra_forms if f.is_bound):
            item.name = name
            item.report_values = values_from(report_form)
            if setup_form is not None:
                item.setup_values = values_from(setup_form)
            if probes is not None and probes.is_bound:
                item.probe_columns, item.group_columns = columns_from(probes, groups)
            try:
                with transaction.atomic():
                    item.save()
                    if request.POST.get('in_use'):
                        item.use()
            except IntegrityError:
                errors.append(f'There is already a {rtype.label} defaults set called "{name}".')
            else:
                messages.success(request, f'"{item.name}" saved.')
                return redirect('edit-defaults', pk=item.pk)
    # The report editor's sections, in its order: field sections, the weld grid, the setup block
    field_sections = {key: names for key, _, names in report_fields(item.report_type)}
    sections = []
    for key, title, _ in REPORT_SECTIONS:
        if key not in rtype.sections:
            continue
        if key in field_sections:
            sections.append({'key': key, 'title': title, 'fields': [report_form[n] for n in field_sections[key]]})
        elif key == 'equipment' and probes is not None:
            sections.append({'key': key, 'title': title, 'part': 'equipment'})
        elif key == 'materials':
            sections.append({'key': key, 'title': title, 'part': 'materials'})
        elif key == 'setups' and setup_form is not None:
            sections.append({'key': key, 'title': 'Every new setup', 'part': 'setups'})
    return render(request, 'reports/edit_defaults.html', {
        'item': item, 'rtype': rtype, 'report_form': report_form, 'setup_form': setup_form,
        'probe_formset': probes, 'group_formset': groups, 'weld_grid': weld_grid_rows(),
        'sensitivity_blocks': library_blocks() if 'materials' in rtype.sections else {},
        'has_errors': report_form.errors or any(f.is_bound and not f.is_valid() for f in extra_forms),
        'sections': sections, 'errors': errors,
        'name_value': request.POST.get('defaults_name', item.name) if request.method == 'POST' else item.name,
    })
