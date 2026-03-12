from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from .services.document_processor import WordTemplateProcessor
import os
from .forms import ReportForm, SetupForm
from .models import Report, Setup


def home(request):
    """
    Landing page at root url
    """
    return render(request, 'reports/home.html')

def create_report(request):
    """
    Create new full report
    """
    if request.method == 'POST':
        form = ReportForm(request.POST)
        setup_form = SetupForm(request.POST)
        if form.is_valid() and setup_form.is_valid():
            report = form.save()                      
            setup = setup_form.save(commit=False)     
            setup.report = report                     
            setup.save()                              
            return redirect('report-list')
    else:
        form = ReportForm()
        setup_form = SetupForm()
    return render(request, 'reports/create_report.html', {'form': form, 'setup_form': setup_form})

def setup_list(request):
    """
    View all setups that are currently in the database
    """
    setups = Setup.objects.all()
    return render(request, 'reports/setup_list.html', {'setups': setups})

def edit_setup(request, pk):
    """
    Edit a single setup from the setup list
    """
    setup = get_object_or_404(Setup, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            setup.delete()
            return redirect('setup-list')
        form = SetupForm(request.POST, instance=setup)
        if form.is_valid():
            form.save()
            return redirect('setup-list')
    else:
        form = SetupForm(instance=setup)
    return render(request, 'reports/edit_setup.html', {'form': form, 'setup': setup})

def report_list(request):
    """
    View all report information stored within the database
    """
    reports = Report.objects.all()
    return render(request, 'reports/report_list.html', {'reports': reports})