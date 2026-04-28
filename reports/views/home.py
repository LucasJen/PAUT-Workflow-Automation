from django.shortcuts import render


def home(request):
    """
    Landing page at root url
    """
    return render(request, 'reports/home.html')
