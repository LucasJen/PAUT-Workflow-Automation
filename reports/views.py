from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from datetime import datetime

def home(request):
    """Simple Hello World view"""
    context = {
        'current_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    return render(request, 'reports/home.html', context)

def create_hic_report(request):
    """Create HIC Report - Long form"""
    
    if request.method == 'POST':
        # We'll handle form submission later
        # For now, just acknowledge it
        print("Form submitted!")
        # TODO: Process form data
        pass
    
    # GET request - show empty form
    context = {
        'page_title': 'Create HIC Report',
    }
    return render(request, 'reports/create_hic.html', context)