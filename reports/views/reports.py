from django.http import FileResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from ..services.report_render import render_report
from ..forms import (
    PersonFormSet, ReportForm, SetupFormSet, comparison_formset, drawing_formset, scan_image_formset,
)
from ..models import Report, ReportImage, ReportPerson, Setup, SetupImage, ResultsTable, ResultsRow
from ..report_types import get_report_type
from ..results import fit_to_columns, report_results, report_scan_rows, scan_rows
from django.core.exceptions import ValidationError
from django.forms import ImageField
from ..report_types import REPORT_TYPES
import io
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

DOCX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


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


def _save_ordered_formset(formset, **fields):
    """
    Saves an inline formset, deleting removed objects and numbering the rest
    by their position on the page. `fields` are set on every saved object (e.g. kind=...).
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
        for name, value in fields.items():
            setattr(f.instance, name, value)
        f.instance.save()
        order += 1


def _save_results_table(report, columns, rows):
    ResultsTable.objects.filter(report=report).delete()
    if columns:
        rt = ResultsTable.objects.create(report=report, columns=columns)
        ResultsRow.objects.bulk_create(
            ResultsRow(table=rt, cells=cells, order=i) for i, cells in enumerate(rows)
        )


def _setup_image_uploads(request, setup_formset):
    """
    Calibration screenshots uploaded per setup block (file input '<prefix>-cal_images').
    Returns {form: [validated files]}; adds an error to the setup form for non-image files.
    """
    uploads, validator = {}, ImageField()
    for f in setup_formset.forms:
        files = request.FILES.getlist(f.add_prefix('cal_images'))
        valid = []
        for file in files:
            try:
                valid.append(validator.clean(file))
            except ValidationError:
                f.add_error(None, f'"{file.name}" is not an image, so it was not added as a calibration screenshot.')
        if valid:
            uploads[f] = valid
    return uploads


def _save_setup_images(request, report, setup_formset, uploads):
    remove = [pk for pk in request.POST.getlist('remove_setup_image') if pk.isdigit()]
    SetupImage.objects.filter(pk__in=remove, setup__report=report).delete()
    for f, files in uploads.items():
        setup = f.instance
        if setup.pk is None or f in setup_formset.deleted_forms:
            continue
        start = setup.images.count()
        for i, file in enumerate(files):
            SetupImage.objects.create(setup=setup, image=file, order=start + i)


def _known_people():
    """(name, certification) of everyone on earlier reports, latest certification per name."""
    latest = {}
    for name, certification in ReportPerson.objects.order_by('pk').values_list('name', 'certification'):
        latest[name.strip()] = certification
    return sorted(latest.items(), key=lambda item: item[0].lower())


def _get_report(pk):
    """The Report with this pk (from a query string or form field), or None."""
    return Report.objects.filter(pk=pk).first() if pk and str(pk).isdigit() else None


def create_report(request):
    """
    Takes user input to either save the input as report and setup information or to generate a report
    """
    results_data = {}

    if request.method == 'POST':
        # Bind to the loaded report (if any) so saving updates it instead of creating a copy
        instance = _get_report(request.POST.get('report_id'))

        results, results_ok = None, True
        try:
            results = _parse_results(request.POST)
        except ValueError:
            results_ok = False
            messages.error(request, 'The results table data could not be read. Please re-enter it and try again.')
        if results:
            # Fixed-column report types always store their own headings in their own order
            headings = get_report_type(request.POST.get('report_type')).results_headings
            results = fit_to_columns(*results, headings) if results[0] else results
            results_data = {'columns': results[0], 'rows': results[1]}
        scan_ids = [scan_id for scan_id, _ in (scan_rows(*results) if results else report_scan_rows(instance))]

        form = ReportForm(request.POST, instance=instance)
        setup_formset = SetupFormSet(request.POST, instance=form.instance)
        people = PersonFormSet(request.POST, instance=form.instance, prefix='people')
        drawings = drawing_formset(request.POST, request.FILES, instance=form.instance)
        image_formset = scan_image_formset(request.POST, request.FILES, instance=form.instance, scan_ids=scan_ids)
        comparisons = comparison_formset(request.POST, request.FILES, instance=form.instance)
        formsets = (setup_formset, people, drawings, image_formset, comparisons)

        valid = form.is_valid() and all(fs.is_valid() for fs in formsets) and results_ok
        if valid:
            # Checked after the formsets so each file's error can be shown on its setup block
            setup_uploads = _setup_image_uploads(request, setup_formset)
            valid = not any(f.errors for f in setup_formset.forms)
        if valid:
            with transaction.atomic():
                report = form.save()
                _save_ordered_formset(setup_formset)
                _save_setup_images(request, report, setup_formset, setup_uploads)
                _save_ordered_formset(people)
                _save_ordered_formset(drawings, kind=ReportImage.DRAWING)
                _save_ordered_formset(image_formset, kind=ReportImage.SCAN)
                _save_ordered_formset(comparisons, kind=ReportImage.COMPARISON)
                if results is not None:
                    _save_results_table(report, *results)

            if 'generate' in request.POST and not report.setups.exists():
                messages.success(request, 'Report saved.')
                messages.error(request, 'Add at least one UT setup before generating the report.')
                return redirect(f"{reverse('create-report')}?loaded={report.pk}")
            if 'generate' in request.POST:
                # Back to the editor, which starts the download; downloading straight from this
                # POST would leave the page showing the pre-save (possibly unsaved-new) form
                messages.success(request, 'Report saved. Your download will start shortly.')
                return redirect(f"{reverse('create-report')}?loaded={report.pk}&download=1")
            messages.success(request, 'Report saved.')
            return redirect(f"{reverse('create-report')}?loaded={report.pk}")
        messages.error(request, 'The report was not saved. Check the highlighted fields.')
    else:
        loaded_report = _get_report(request.GET.get('loaded'))
        form = ReportForm(instance=loaded_report)
        setup_formset = SetupFormSet(instance=loaded_report)
        people = PersonFormSet(instance=loaded_report, prefix='people')
        drawings = drawing_formset(instance=loaded_report)
        comparisons = comparison_formset(instance=loaded_report)
        scan_ids = [scan_id for scan_id, _ in report_scan_rows(loaded_report)]
        image_formset = scan_image_formset(instance=loaded_report, scan_ids=scan_ids)
        if loaded_report is not None and hasattr(loaded_report, 'results_table'):
            columns, rows = report_results(loaded_report)
            results_data = {'columns': columns, 'rows': rows}

    return render(request, 'reports/create_report.html', {
        'form': form,
        'setup_formset': setup_formset,
        'person_formset': people,
        'drawing_formset': drawings,
        'image_formset': image_formset,
        'comparison_formset': comparisons,
        'known_people': _known_people(),
        'results_data': results_data,
        'report_types': {key: t.as_json() for key, t in REPORT_TYPES.items()},
        'saved_setups': _saved_setup_choices(),
        'saved_setup_values': _saved_setup_values(),
    })


def _saved_setup_choices():
    """Setups offered in each setup block's 'Load from…' menu, saved ones first."""
    setups = Setup.objects.order_by('report_id', '-pk')
    return {
        'saved': [s for s in setups if s.report_id is None],
        'in_reports': [s for s in setups if s.report_id is not None],
    }


def _saved_setup_values():
    """{pk: {field: value}} for filling a setup block from a saved setup in the browser."""
    excluded = {'id', 'report', 'order'}
    names = [f.name for f in Setup._meta.concrete_fields if f.name not in excluded]
    return {s['id']: {n: s[n] for n in names} for s in Setup.objects.values('id', *names)}


def generate_report(request, pk):
    """
    Renders the report's Word template (per report type) and returns it as a download
    """
    report = get_object_or_404(Report, pk=pk)

    if not report.setups.exists():
        messages.error(request, 'Add at least one UT setup before generating the report.')
        return redirect(f"{reverse('create-report')}?loaded={pk}")

    output_name = f'{safe_filename(report.document_filename)}.docx'
    content = render_report(report)

    # Optionally keep a copy on the server (REPORT_OUTPUT_DIR = None turns this off)
    if settings.REPORT_OUTPUT_DIR:
        copy_path = os.path.join(settings.REPORT_OUTPUT_DIR, output_name)
        try:
            os.makedirs(settings.REPORT_OUTPUT_DIR, exist_ok=True)
            with open(copy_path, 'wb') as f:
                f.write(content)
        except PermissionError:
            # Usually the previous copy is open in Word; the download still works
            logger.warning('Could not update server copy %s (file in use?)', copy_path)

    return FileResponse(io.BytesIO(content), as_attachment=True, filename=output_name, content_type=DOCX_CONTENT_TYPE)


def report_list(request):
    """
    View all report information stored within the database
    """
    reports = Report.objects.annotate(setup_count=Count('setups')).prefetch_related('people').order_by('-pk')
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            count = Report.objects.filter(pk__in=selected_pks).count()
            Report.objects.filter(pk__in=selected_pks).delete()
            messages.success(request, f"Deleted {count} report{'s' if count != 1 else ''}.")
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
    Old 'new report' URL: the report editor now creates reports on first save
    """
    return redirect('create-report')


def edit_existing_report(request, pk):
    """
    Old edit URL: reports are edited in the full report editor
    """
    report = get_object_or_404(Report, pk=pk)
    return redirect(f"{reverse('create-report')}?loaded={report.pk}")
