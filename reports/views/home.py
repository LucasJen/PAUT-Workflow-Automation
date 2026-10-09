from django.db.models import F
from django.shortcuts import render

from documents.views import dashboard_context
from equipment.cal_due import due_items
from equipment.models import CalibrationBlock, Encoder, Probe, ProbeModel, Scope, SensitivityBlock, WedgeModel
from ..models import Report, Setup


def home(request):
    """
    Dashboard: quick actions, recently edited reports, the documentation libraries (most recently
    used first, searchable with ?q= and filtered by file type with ?type=) and the equipment libraries
    """
    recent_reports = Report.objects.order_by(F('updated_at').desc(nulls_last=True), '-pk')[:8]

    # How many in each library are out of calibration or due within 30 days (a module counts as its scope)
    due = {}
    for item in due_items():
        kind = {'Module': 'Scope'}.get(item['kind'], item['kind'])
        counts = due.setdefault(kind, {'overdue': 0, 'soon': 0})
        counts['overdue' if item['overdue'] else 'soon'] += 1

    # The equipment libraries, in the sidebar's order: (label, icon, url name, count, calibration due counts)
    libraries = [
        ('Scopes', 'display', 'scope-list', Scope.objects.count(), due.get('Scope')),
        ('Probes', 'soundwave', 'probe-list', Probe.objects.count(), due.get('Probe')),
        ('Probe catalogue', 'journal-text', 'probe-model-list', ProbeModel.objects.count(), None),
        ('Wedge catalogue', 'triangle', 'wedge-model-list', WedgeModel.objects.count(), None),
        ('Calibration blocks', 'bricks', 'cal-block-list', CalibrationBlock.objects.count(), due.get('Calibration block')),
        ('Sensitivity blocks', 'box', 'sensitivity-block-list', SensitivityBlock.objects.count(), None),
        ('Encoders', 'record-circle', 'encoder-list', Encoder.objects.count(), due.get('Encoder')),
    ]
    return render(request, 'reports/home.html', {
        'recent_reports': recent_reports,
        **dashboard_context(request),
        'libraries': libraries,
        'stats': {
            'reports': Report.objects.count(),
            'saved_setups': Setup.objects.filter(report__isnull=True).count(),
        },
    })
