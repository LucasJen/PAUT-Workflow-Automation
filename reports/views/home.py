from datetime import date, timedelta

from django.db.models import F
from django.shortcuts import render

from equipment.models import CalibrationBlock, Encoder, Probe, Scope, SensitivityBlock
from ..models import Report, Setup
from ..templatetags.ui import CAL_DUE_SOON_DAYS


def home(request):
    """
    Dashboard: quick actions, recently edited reports and scopes due for calibration
    """
    recent_reports = Report.objects.order_by(F('updated_at').desc(nulls_last=True), '-pk')[:8]
    cal_due = Scope.objects.filter(
        calibration_due_date__lte=date.today() + timedelta(days=CAL_DUE_SOON_DAYS),
    ).order_by('calibration_due_date')

    equipment_count = sum(m.objects.count() for m in (Scope, Probe, CalibrationBlock, SensitivityBlock, Encoder))
    return render(request, 'reports/home.html', {
        'recent_reports': recent_reports,
        'cal_due': cal_due,
        'stats': {
            'reports': Report.objects.count(),
            'saved_setups': Setup.objects.filter(report__isnull=True).count(),
            'equipment': equipment_count,
            'cal_due': cal_due.count(),
        },
    })
