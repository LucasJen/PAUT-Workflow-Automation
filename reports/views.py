from django.shortcuts import render
from datetime import datetime

def home(request):
    """Simple Hello World view"""
    context = {
        'current_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    return render(request, 'reports/home.html', context)

