from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.conf import settings
from ..services.document_processor import WordTemplateProcessor
from ..forms import ReportForm, SetupForm, SetupFormSet, ImageFormSet
from ..models import Report, Setup, ResultsTable, ResultsRow
import json
import os


def create_report(request):
    """
    Takes user input to either save the input as report and setup information or to generate a report
    """
    results_data = {}

    if request.method == 'POST':
        form = ReportForm(request.POST)
        if form.is_valid():
            report = form.save()

            setup_formset = SetupFormSet(request.POST, instance=report)
            if setup_formset.is_valid():
                instances = setup_formset.save(commit=False)
                for i, inst in enumerate(instances):
                    inst.order = i
                    inst.save()
                for obj in setup_formset.deleted_objects:
                    obj.delete()

            image_formset = ImageFormSet(request.POST, request.FILES, instance=report)
            if image_formset.is_valid():
                instances = image_formset.save(commit=False)
                for i, inst in enumerate(instances):
                    inst.order = i
                    inst.save()
                for obj in image_formset.deleted_objects:
                    obj.delete()

            try:
                columns = json.loads(request.POST.get('results_columns', '[]'))
                rows = json.loads(request.POST.get('results_rows', '[]'))
                if columns:
                    rt = ResultsTable.objects.create(report=report, columns=columns)
                    for i, cells in enumerate(rows):
                        ResultsRow.objects.create(table=rt, cells=cells, order=i)
            except Exception:
                pass

            if 'generate' in request.POST:
                return redirect('generate-report', pk=report.pk)
            return redirect('report-list')
        else:
            setup_formset = SetupFormSet(request.POST)
            image_formset = ImageFormSet(request.POST, request.FILES)
    else:
        loaded_pk = request.GET.get('loaded')
        if loaded_pk:
            try:
                loaded_report = Report.objects.get(pk=loaded_pk)
                form = ReportForm(instance=loaded_report)
                setup_formset = SetupFormSet(instance=loaded_report)
                image_formset = ImageFormSet(instance=loaded_report)
                if hasattr(loaded_report, 'results_table'):
                    rt = loaded_report.results_table
                    results_data = {
                        'columns': rt.columns,
                        'rows': [r.cells for r in rt.rows.all()],
                    }
            except Report.DoesNotExist:
                form = ReportForm()
                setup_formset = SetupFormSet()
                image_formset = ImageFormSet()
        else:
            form = ReportForm()
            setup_formset = SetupFormSet()
            image_formset = ImageFormSet()

    reports = Report.objects.order_by('-pk')
    setups = Setup.objects.all()
    return render(request, 'reports/create_report.html', {
        'form': form,
        'setup_formset': setup_formset,
        'image_formset': image_formset,
        'results_data_json': json.dumps(results_data),
        'reports': reports,
        'setups': setups,
    })


def generate_report(request, pk):
    """
    Calls find and replace functions to act on a report template
    """
    report = get_object_or_404(Report, pk=pk)
    setups = list(report.setups.order_by('order'))

    if not setups:
        return redirect('create-report')

    template_path = os.path.join(settings.BASE_DIR, 'word_templates', 'long_form_template.docx')
    output_path = os.path.join(settings.BASE_DIR, 'outputs', f'{report.document_filename}.docx')

    processor = WordTemplateProcessor(template_path, output_path)

    report_excluded = {'id', 'document_filename'}
    setup_excluded = {'id', 'report', 'order'}

    # Replace report-level placeholders
    for field in report._meta.concrete_fields:
        if field.name in report_excluded:
            continue
        value = getattr(report, field.name, '')
        placeholder = f'{{{{{field.name.upper()}}}}}'
        processor.replace(placeholder, str(value) if value else '')

    # Multi-setup: duplicate setup table block per setup
    if processor._find_table_with_placeholder('{{SETUP_TABLE}}') is not None:
        processor.populate_setup_tables(setups)
    else:
        # Fallback: populate single setup table using first setup's fields
        setup = setups[0]
        for setup_field in setup._meta.concrete_fields:
            if setup_field.name in setup_excluded:
                continue
            setup_value = getattr(setup, setup_field.name)
            setup_placeholder = f'{{{{{setup_field.name.upper()}}}}}'
            processor.replace(setup_placeholder, str(setup_value) if setup_value else '')

    # Images
    images = list(report.images.order_by('order'))
    if images:
        processor.insert_images(images)

    # Results table
    results_table = getattr(report, 'results_table', None)
    if results_table is not None:
        processor.populate_results_table(results_table)

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
