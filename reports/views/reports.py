from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.conf import settings
from ..services.document_processor import WordTemplateProcessor
from ..forms import ReportForm, SetupForm
from ..models import Report, Setup
import os


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
            if 'generate' in request.POST:
                return redirect('generate-report', pk=report.pk)
            return redirect('report-list')
    else:
        loaded_pk = request.GET.get('loaded')
        if loaded_pk:
            try:
                loaded_report = Report.objects.get(pk=loaded_pk)
                form = ReportForm(instance=loaded_report)
                loaded_setup = loaded_report.setups.first()
                setup_form = SetupForm(instance=loaded_setup) if loaded_setup else SetupForm()
            except Report.DoesNotExist:
                form = ReportForm()
                setup_form = SetupForm()
        else:
            form = ReportForm()
            setup_form = SetupForm()

    reports = Report.objects.order_by('-pk')
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

    if setup is None:
        return redirect('create-report')

    template_path = os.path.join(settings.BASE_DIR, 'word_templates', 'long_form_template.docx')
    output_path = os.path.join(settings.BASE_DIR, 'outputs', f'{report.document_filename}.docx')

    # TODO will likely make this selectable by user to allow different report formats.
    processor = WordTemplateProcessor(template_path, output_path)

    report_excluded = {'id', 'document_filename'}
    setup_excluded = {'id', 'report'}

    for field in report._meta.concrete_fields:
        if field.name in report_excluded:
            continue
        value = getattr(report, field.name, '')
        placeholder = f'{{{{{field.name.upper()}}}}}' # Placeholder format: {{example_placeholder}}
        processor.replace(placeholder, str(value) if value else '')

    for setup_field in setup._meta.concrete_fields:
        if setup_field.name in setup_excluded:
            continue
        setup_value = getattr(setup, setup_field.name)
        setup_placeholder = f'{{{{{setup_field.name.upper()}}}}}' # Placeholder format: {{example_placeholder}}
        processor.replace(setup_placeholder, str(setup_value) if setup_value else '')

    try:
        processor.save()
    except PermissionError:
        messages.error(request, 'A report with that name already exists in the output folder and is currently open. Close the file and try again.')
        return redirect(f"{reverse('create-report')}?loaded={pk}")

    return redirect(f"{reverse('create-report')}?loaded={pk}")


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


def new_report(request):
    """
    Creates a blank report and redirects to the edit view
    """
    report = Report.objects.create()
    return redirect('edit-report', pk=report.pk)


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
