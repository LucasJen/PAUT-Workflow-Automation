from django import template

register = template.Library()


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
