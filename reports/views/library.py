"""Library › Defaults: named sets of starting values per report type, one in use per type."""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from ..defaults import report_defaults_form, report_fields, setup_defaults_form, values_from
from ..models import ReportDefaults
from ..report_types import REPORT_TYPES


def defaults_list(request):
    if request.method == 'POST':
        item = get_object_or_404(ReportDefaults, pk=request.POST.get('pk'))
        label = REPORT_TYPES[item.report_type].label if item.report_type in REPORT_TYPES else item.report_type
        if 'use' in request.POST:
            item.use()
            messages.success(request, f'New {label} reports now start from "{item.name}".')
        elif 'duplicate' in request.POST:
            copy = ReportDefaults(name=_free_name(item.report_type, f'{item.name} (copy)'), report_type=item.report_type,
                                  report_values=item.report_values, setup_values=item.setup_values)
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
    if request.method == 'POST':
        report_form = report_defaults_form(item.report_type, request.POST)
        setup_form = setup_defaults_form(request.POST)
        name = (request.POST.get('defaults_name') or '').strip()
        if not name:
            errors.append('Give these defaults a name.')
        if not errors and report_form.is_valid() and setup_form.is_valid():
            item.name = name
            item.report_values, item.setup_values = values_from(report_form), values_from(setup_form)
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
    else:
        report_form = report_defaults_form(item.report_type, initial=item.report_values)
        setup_form = setup_defaults_form(initial=item.setup_values)
    sections = [(title, [report_form[n] for n in names]) for title, names in report_fields(item.report_type)]
    return render(request, 'reports/edit_defaults.html', {
        'item': item, 'rtype': rtype, 'report_form': report_form, 'setup_form': setup_form,
        'sections': sections, 'errors': errors,
        'name_value': request.POST.get('defaults_name', item.name) if request.method == 'POST' else item.name,
    })
