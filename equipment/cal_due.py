"""
Calibration due tracking: what in the inventory is out of calibration or due soon (the dashboard's
Calibration due card), and the warning when equipment named in a report was out of calibration
on its test date (the report editor and the download).
"""
from datetime import date, datetime, timedelta

from django.urls import reverse

from .models import CalibrationBlock, Encoder, Probe, Scope

DUE_SOON_DAYS = 30   # as the lists' badges (reports.templatetags.ui.CAL_DUE_SOON_DAYS)

TEXT_DATE_FORMATS = ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y', '%b %d, %Y', '%B %d, %Y', '%d-%b-%Y', '%d-%b-%y')


def parse_text_date(text):
    """A date typed into a report's text field (e.g. '3/15/2027'), or None ('N/A', blank, anything else)."""
    text = (text or '').strip()
    for fmt in TEXT_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _items():
    """(kind, name, serial, due date, edit url) of every calibration due date in the inventory."""
    for scope in Scope.objects.exclude(calibration_due_date=None, module_cal_due=None):
        name = scope.name or scope.model or 'Scope'
        url = reverse('edit-scope', args=[scope.pk])
        if scope.calibration_due_date:
            yield 'Scope', name, scope.serial_number, scope.calibration_due_date, url
        if scope.module_cal_due:
            yield 'Module', scope.module_model or f'{name} module', scope.module_serial, scope.module_cal_due, url
    for probe in Probe.objects.exclude(calibration_due_date=None):
        yield 'Probe', probe.model or 'Probe', probe.serial_number, probe.calibration_due_date, \
            reverse('edit-probe', args=[probe.pk])
    for block in CalibrationBlock.objects.exclude(calibration_due_date=None):
        yield 'Calibration block', block.block_type or 'Block', block.serial_number, block.calibration_due_date, \
            reverse('edit-cal-block', args=[block.pk])
    for encoder in Encoder.objects.exclude(calibration_due_date=None):
        yield 'Encoder', encoder.model or 'Encoder', encoder.serial_number, encoder.calibration_due_date, \
            reverse('edit-encoder', args=[encoder.pk])


def due_items(days=DUE_SOON_DAYS, today=None):
    """Equipment out of calibration or due within `days`, soonest first: [{kind, name, serial, due, overdue, url}]."""
    today = today or date.today()
    limit = today + timedelta(days=days)
    found = [{'kind': kind, 'name': name, 'serial': serial, 'due': due, 'overdue': due < today, 'url': url}
             for kind, name, serial, due, url in _items() if due <= limit]
    return sorted(found, key=lambda item: item['due'])


def test_day(report):
    """The day the equipment had to be in calibration: the last test day, else the report date, else today."""
    return report.test_end_date or report.test_date or report.report_date or date.today()


def _serials(values):
    return {v.strip().upper() for v in values if v and v.strip() and v.strip().upper() not in ('N/A', 'NA', '-')}


def report_cal_warnings(report):
    """
    Warnings for equipment named in the report whose calibration was due before its test day:
    the inventory's records found by serial number (scopes and modules, probes, calibration
    blocks), and the cal. due dates typed on the report itself.
    """
    if report.pk is None:
        return []
    day = test_day(report)
    when = f'{day:%b} {day.day}, {day.year}'
    setups = list(report.setups.all())
    scope_serials = _serials([report.inst_serial, *(s.scope_serial for s in setups)])
    module_serials = _serials([report.inst_module_serial, *(s.module_serial for s in setups)])
    probe_serials = _serials([*(p.serial for p in report.probes.all()), *(s.transducer_serial for s in setups)])
    block_serials = _serials([getattr(report, 'add1_serial', ''), getattr(report, 'add2_serial', ''),
                              *(s.cal_block_serial for s in setups)])

    warnings = []

    def out_of_cal(what, serial, due):
        if due and due < day:
            warnings.append(f'{what} S/N {serial} was out of calibration (due {due:%b} {due.day}, {due.year}) '
                            f'on the test date, {when}.')

    for scope in Scope.objects.all():
        serial = scope.serial_number.strip().upper()
        if serial and serial in scope_serials:
            out_of_cal(f'Scope {scope.name or scope.model}'.strip(), scope.serial_number, scope.calibration_due_date)
        module = scope.module_serial.strip().upper()
        if module and module in module_serials:
            out_of_cal(f'Module {scope.module_model}'.strip(), scope.module_serial, scope.module_cal_due)
    for probe in Probe.objects.exclude(calibration_due_date=None):
        if probe.serial_number.strip().upper() in probe_serials:
            out_of_cal(f'Probe {probe.model}'.strip(), probe.serial_number, probe.calibration_due_date)
    for block in CalibrationBlock.objects.exclude(calibration_due_date=None):
        if block.serial_number.strip().upper() in block_serials:
            out_of_cal(f'Calibration block {block.block_type}'.strip(), block.serial_number, block.calibration_due_date)

    # The due dates printed on the report (weld form instrument table, each setup's details)
    typed = [('Instrument cal. due date', report.inst_cal_due), ('Module cal. due date', report.inst_module_cal_due)]
    for number, setup in enumerate(setups, 1):
        typed += [(f'Setup {number} instrument cal. due', setup.scope_cal_due),
                  (f'Setup {number} module cal. due', setup.module_cal_due)]
    for label, text in typed:
        due = parse_text_date(text)
        if due and due < day:
            warnings.append(f'{label} on the report ({text.strip()}) is before the test date, {when}.')
    return list(dict.fromkeys(warnings))
