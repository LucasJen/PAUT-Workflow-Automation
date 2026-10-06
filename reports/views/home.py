from django.db.models import F
from django.shortcuts import render

from documents.views import dashboard_documents
from equipment.models import CalibrationBlock, Encoder, Probe, ProbeModel, Scope, SensitivityBlock, WedgeModel
from ..models import Report, Setup


def home(request):
    """
    Dashboard: quick actions, recently edited reports, the documentation libraries (most recently
    used first, searchable with ?q=) and the equipment libraries
    """
    recent_reports = Report.objects.order_by(F('updated_at').desc(nulls_last=True), '-pk')[:8]
    doc_query = request.GET.get('q', '')

    # The equipment libraries, in the sidebar's order: (label, icon, url name, count)
    libraries = [
        ('Scopes', 'display', 'scope-list', Scope.objects.count()),
        ('Probes', 'soundwave', 'probe-list', Probe.objects.count()),
        ('Probe catalogue', 'journal-text', 'probe-model-list', ProbeModel.objects.count()),
        ('Wedge catalogue', 'triangle', 'wedge-model-list', WedgeModel.objects.count()),
        ('Calibration blocks', 'bricks', 'cal-block-list', CalibrationBlock.objects.count()),
        ('Sensitivity blocks', 'box', 'sensitivity-block-list', SensitivityBlock.objects.count()),
        ('Encoders', 'record-circle', 'encoder-list', Encoder.objects.count()),
    ]
    return render(request, 'reports/home.html', {
        'recent_reports': recent_reports,
        'documents': dashboard_documents(doc_query),
        'query': doc_query,
        'libraries': libraries,
        'stats': {
            'reports': Report.objects.count(),
            'saved_setups': Setup.objects.filter(report__isnull=True).count(),
        },
    })
