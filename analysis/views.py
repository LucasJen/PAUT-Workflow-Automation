from django.shortcuts import render

from .paths import allowed_roots


def analysis(request):
    """The Analysis page: open an .nde file and look through its data, like OmniPC."""
    return render(request, 'analysis/analysis.html', {'roots': allowed_roots()})
