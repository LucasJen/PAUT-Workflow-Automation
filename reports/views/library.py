"""Library › Defaults: the starting values of each report type."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.http import Http404

from ..defaults import (
    defaults_for, report_defaults_form, report_fields, setup_defaults_form, values_from,
)
from ..models import ReportDefaults
from ..report_types import REPORT_TYPES


def defaults_list(request):
    saved = {d.report_type: d for d in ReportDefaults.objects.all()}
    items = [{'type': rtype, 'record': saved.get(key)} for key, rtype in REPORT_TYPES.items()]
    return render(request, 'reports/defaults_list.html', {'items': items})


def edit_defaults(request, report_type):
    if report_type not in REPORT_TYPES:
        raise Http404
    rtype = REPORT_TYPES[report_type]
    report_values, setup_values = defaults_for(report_type)
    if request.method == 'POST':
        report_form = report_defaults_form(report_type, request.POST)
        setup_form = setup_defaults_form(request.POST)
        if report_form.is_valid() and setup_form.is_valid():
            ReportDefaults.objects.update_or_create(report_type=report_type, defaults={
                'report_values': values_from(report_form), 'setup_values': values_from(setup_form),
            })
            messages.success(request, f'Defaults for {rtype.label} saved.')
            return redirect('edit-defaults', report_type=report_type)
    else:
        report_form = report_defaults_form(report_type, initial=report_values)
        setup_form = setup_defaults_form(initial=setup_values)
    sections = [(title, [report_form[n] for n in names]) for title, names in report_fields(report_type)]
    return render(request, 'reports/edit_defaults.html', {
        'rtype': rtype, 'report_form': report_form, 'setup_form': setup_form, 'sections': sections,
    })
