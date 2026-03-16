from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from .services.document_processor import WordTemplateProcessor
from .forms import ReportForm, SetupForm
from .models import Report, Setup
import os


def home(request):
    """
    Landing page at root url
    """
    return render(request, 'reports/home.html')

def create_report(request):
    """
    Takes user input to either save the input as report and setup information or to generate a report
    """
    if request.method == 'POST':
        form = ReportForm(request.POST)
        setup_form = SetupForm(request.POST)
        if form.is_valid() and setup_form.is_valid():
            report = form.save()
            setup = setup_form.save(commit=False)
            setup.report = report
            setup.save()
            print("setup save")
            print(setup)
            # If generate report button is pressed, will run the generate report view
            if 'generate' in request.POST:
                return redirect('generate-report', pk=report.pk)
            return redirect('report-list')
    else:
        form = ReportForm()
        setup_form = SetupForm()
    
    reports = Report.objects.all()
    setups = Setup.objects.all()
    return render(request, 'reports/create_report.html', {
        'form': form,
        'setup_form': setup_form,
        'reports': reports,
        'setups': setups
    })

def generate_report(request, pk):
    """
    Calls find and replace functions to act on a report template
    """
    report = get_object_or_404(Report, pk=pk)
    setup = report.setups.first()

    template_path = os.path.join(settings.BASE_DIR, 'word_templates', 'long_form_template.docx')
    output_path = os.path.join(settings.BASE_DIR, 'outputs', f'{report.document_filename}.docx')

    # Creates object to define the input document and output location
    # TODO will likely make this selectable by user to allow different report formats.
    processor = WordTemplateProcessor(template_path, output_path)

    # Excluded fields are not ran during the find and replace function.
    excluded_fields = {'id', 'document_filename'}

    # uses the model's meta object to match field names to their respective placeholder
    for field in report._meta.concrete_fields:
        if field.name in excluded_fields:
            continue
        value = getattr(report, field.name, '')
        placeholder = f'{{{{{field.name.upper()}}}}}' # Placeholder format: {{example_placeholder}}
        processor.replace(placeholder, str(value) if value else '')
        print(f'Replaced {field.name}')

    for setup_field in setup._meta.concrete_fields:
        if setup_field.name in excluded_fields:
            continue
        setup_value = getattr(setup, setup_field.name)
        setup_placeholder = f'{{{{{setup_field.name.upper()}}}}}' # Placeholder format: {{example_placeholder}}
        processor.replace(setup_placeholder, str(setup_value) if setup_value else '')
        print(f'Replaced {setup_field.name}')

    processor.save()
    return redirect('create-report')

def setup_list(request):
    """
    View all setups that are currently in the database, references Setup model
    """
    setups = Setup.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected_setups')
        if 'delete' in request.POST:
            Setup.objects.filter(pk__in=selected_pks).delete()
            return redirect('setup-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-setup', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(Setup, pk=selected_pks[0])
            original.pk = None  # clears the pk, forcing a new row on save
            original.save()
            return redirect('setup-list')
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

def edit_existing_report(request, pk):
    """
    Edit a single report from the report list
    """
    report = get_object_or_404(Report, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            report.delete()
            return redirect('report-list')
        form = ReportForm(request.POST, instance=report)
        if form.is_valid():
            form.save()
            return redirect('report-list')
    else:
        form = ReportForm(instance=report)
    return render(request, 'reports/edit_report.html', {'form': form, 'report': report})

def report_list(request):
    """
    View all report information stored within the database
    """
    reports = Report.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected_reports')
        if 'delete' in request.POST:
            Report.objects.filter(pk__in=selected_pks).delete()
            return redirect('report-list')
        if 'edit' in request.POST and len(selected_pks) == 1:
            return redirect('edit-report', pk=selected_pks[0])
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(Report, pk=selected_pks[0])
            original.pk = None
            original.save()
            return redirect('report-list')
    return render(request, 'reports/report_list.html', {'reports': reports})