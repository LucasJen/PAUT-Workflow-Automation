from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.conf import settings
from django.db import transaction
from ..services.document_processor import WordTemplateProcessor
from ..forms import ReportForm, SetupForm, SetupFormSet, ImageFormSet
from ..models import Report, Setup, ResultsTable, ResultsRow
import json
import os
import re


_WINDOWS_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def safe_filename(name, default='report'):
    """
    Turns a user-entered document name into a single safe file name (no directories,
    no characters Windows rejects), so generated reports always land in outputs/.
    """
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or '').strip().strip('.').strip()
    if not name or name.upper() in _WINDOWS_RESERVED:
        return default
    return name[:150]


def _parse_results(post):
    """
    Returns (columns, rows) from the hidden results-table inputs, or None if the
    inputs were not submitted. Raises ValueError on malformed data.
    """
    raw_columns = post.get('results_columns')
    if not raw_columns:
        return None
    columns = json.loads(raw_columns)
    rows = json.loads(post.get('results_rows') or '[]')
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        raise ValueError('columns must be a list of strings')
    if not isinstance(rows, list) or not all(
        isinstance(r, list) and all(isinstance(c, str) for c in r) for r in rows
    ):
        raise ValueError('rows must be a list of lists of strings')
    return columns, rows


def _save_ordered_formset(formset):
    """
    Saves an inline formset, deleting removed objects and numbering the rest
    by their position on the page.
    """
    formset.save(commit=False)
    for obj in formset.deleted_objects:
        obj.delete()
    deleted_forms = formset.deleted_forms
    order = 0
    for f in formset.forms:
        if f in deleted_forms or (f.instance.pk is None and not f.has_changed()):
            continue
        f.instance.order = order
        f.instance.save()
        order += 1


def _save_results_table(report, columns, rows):
    ResultsTable.objects.filter(report=report).delete()
    if columns:
        rt = ResultsTable.objects.create(report=report, columns=columns)
        ResultsRow.objects.bulk_create(
            ResultsRow(table=rt, cells=cells, order=i) for i, cells in enumerate(rows)
        )


def create_report(request):
    """
    Takes user input to either save the input as report and setup information or to generate a report
    """
    results_data = {}

    if request.method == 'POST':
        # Bind to the loaded report (if any) so saving updates it instead of creating a copy
        report_id = request.POST.get('report_id')
        instance = Report.objects.filter(pk=report_id).first() if report_id else None

        form = ReportForm(request.POST, instance=instance)
        setup_formset = SetupFormSet(request.POST, instance=form.instance)
        image_formset = ImageFormSet(request.POST, request.FILES, instance=form.instance)

        results, results_ok = None, True
        try:
            results = _parse_results(request.POST)
        except ValueError:
            results_ok = False
            messages.error(request, 'The results table data could not be read. Please re-enter it and try again.')
        if results:
            results_data = {'columns': results[0], 'rows': results[1]}

        if form.is_valid() and setup_formset.is_valid() and image_formset.is_valid() and results_ok:
            with transaction.atomic():
                report = form.save()
                _save_ordered_formset(setup_formset)
                _save_ordered_formset(image_formset)
                if results is not None:
                    _save_results_table(report, *results)

            if 'generate' in request.POST:
                return redirect('generate-report', pk=report.pk)
            return redirect('report-list')
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
        messages.error(request, 'Add at least one UT setup before generating the report.')
        return redirect(f"{reverse('create-report')}?loaded={pk}")

    template_path = os.path.join(settings.BASE_DIR, 'word_templates', 'long_form_template.docx')
    output_path = os.path.join(settings.REPORT_OUTPUT_DIR, f'{safe_filename(report.document_filename)}.docx')

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

    # Images (always called so the {{IMAGE_BLOCK}} sentinel is cleared when there are none)
    processor.insert_images(list(report.images.order_by('order')))

    # Results table
    results_table = getattr(report, 'results_table', None)
    if results_table is not None:
        processor.populate_results_table(results_table)
    processor.replace('{{RESULTS_TABLE}}', '')

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
    reports = Report.objects.order_by('-pk')
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
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
    return render(request, 'reports/report_list.html', {'items': reports})


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
