from datetime import date, timedelta

from django.db.models import F
from django.shortcuts import render

from equipment.models import CalibrationBlock, Encoder, Probe, ProbeModel, Scope, SensitivityBlock, WedgeModel
from ..models import Report, Setup
from ..templatetags.ui import CAL_DUE_SOON_DAYS


def home(request):
    """
    Dashboard: quick actions, recently edited reports, scopes due for calibration and the
    equipment libraries
    """
    recent_reports = Report.objects.order_by(F('updated_at').desc(nulls_last=True), '-pk')[:8]
    cal_due = Scope.objects.filter(
        calibration_due_date__lte=date.today() + timedelta(days=CAL_DUE_SOON_DAYS),
    ).order_by('calibration_due_date')

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
        'cal_due': cal_due,
        'libraries': libraries,
        'stats': {
            'reports': Report.objects.count(),
            'saved_setups': Setup.objects.filter(report__isnull=True).count(),
        },
    })
