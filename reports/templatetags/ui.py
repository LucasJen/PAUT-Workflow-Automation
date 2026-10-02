import os
from datetime import date

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path):
    """
    Like {% static %}, plus ?v=<file modified time> so browsers fetch a fresh copy
    whenever the file changes instead of reusing a stale cached one.
    """
    url = static(path)
    found = finders.find(path)
    if found:
        return f'{url}?v={int(os.path.getmtime(found))}'
    return url

CAL_DUE_SOON_DAYS = 30


@register.filter
def cal_status(due_date):
    """'overdue', 'soon' (within 30 days), 'ok', or '' when no due date is set."""
    if not due_date:
        return ''
    days = (due_date - date.today()).days
    if days < 0:
        return 'overdue'
    if days <= CAL_DUE_SOON_DAYS:
        return 'soon'
    return 'ok'


@register.filter
def cal_label(due_date):
    """Human description of a calibration due date, e.g. 'Due in 9 days'."""
    if not due_date:
        return ''
    days = (due_date - date.today()).days
    if days < 0:
        return f"Overdue by {-days} day{'s' if days != -1 else ''}"
    if days == 0:
        return 'Due today'
    return f"Due in {days} day{'s' if days != 1 else ''}"


@register.simple_tag(takes_context=True)
def nav_active(context, *url_names):
    """
    Returns 'active' when the current page's URL name is one of `url_names`.
    The report editor opened on a saved report counts as 'edit-report'.
    """
    request = context.get('request')
    match = getattr(request, 'resolver_match', None)
    if match is None:
        return ''
    current = match.url_name
    if current == 'create-report' and request.GET.get('loaded'):
        current = 'edit-report'
    return 'active' if current in url_names else ''


@register.filter
def section_grid(key):
    """The field-grid classes for an editor section (report_types.TWO_COLUMN_SECTIONS: two columns)."""
    from ..report_types import TWO_COLUMN_SECTIONS
    return 'field-grid' if key in TWO_COLUMN_SECTIONS else 'field-grid cols-3'


@register.filter
def bound(form, name):
    """form|bound:'field' -> the form's bound field called `field` (field names from a loop)."""
    return form[name]
