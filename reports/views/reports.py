from django.http import FileResponse, JsonResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib import messages
from django.conf import settings
from django.db import transaction
from django.db.models import Count
from ..services.excel_report import (
    CONTINUATION_ROWS, REPORT_RESULT_ROWS, ExcelReportError, build_workbook, excel_available, output_warnings,
)
from ..services.report_render import render_report
from ..services.word_pdf import WordPdfError, docx_to_pdf, word_available
from ..forms import (
    PersonFormSet, ReportForm, SetupFormSet, drawing_formset, equipment_formsets, scan_image_formset,
)
from ..models import Report, ReportImage, ReportPerson, Setup, SetupImage, ResultsTable, ResultsRow
from ..report_types import DEFAULT_REPORT_TYPE, REPORT_SECTIONS, get_report_type
from ..defaults import all_defaults, defaults_for, in_page_order, only_defaults
from equipment.cal_due import report_cal_warnings
from equipment.inventory import with_library_scope

from ..materials import library_blocks
from ..weld_columns import columns_from_setup
from ..weld_form import NOT_USED, wedge_diameter_for, weld_grid_rows
from ..results import fit_to_columns, report_results, report_scan_rows, scan_rows
from django.core.exceptions import ValidationError
from django.forms import ImageField
from ..report_types import REPORT_TYPES
import io
import json
from datetime import date
import logging
import os
import re

logger = logging.getLogger(__name__)

DOCX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


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


def _save_ordered_formset(formset, skip_new=None, **fields):
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
        if f.instance.pk is None and skip_new is not None and skip_new(f):
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


INDICATION_KEY = re.compile(r'^ind-[a-z0-9]{4,40}$')


def _save_indication_images(request, report, rows):
    """
    The weld form's indication images: a file chosen for an indication (indication_image_<key>)
    replaces its image, a ticked remove_indication_image deletes it, and images of indications no
    longer in the results go too. An indication's key is the cell after its row's Notes.
    """
    images = ReportImage.objects.filter(report=report, kind=ReportImage.INDICATION)
    keys = {str(row[-1]) for row in rows if row and INDICATION_KEY.match(str(row[-1]))}
    images.exclude(scan_id__in=keys).delete()
    images.filter(scan_id__in=request.POST.getlist('remove_indication_image')).delete()
    validator = ImageField()
    for name, files in request.FILES.lists():
        key = name.removeprefix('indication_image_')
        if not name.startswith('indication_image_') or key not in keys or not files:
            continue
        try:
            upload = validator.clean(files[-1])
        except ValidationError:
            messages.error(request, f'{files[-1].name} isn\'t an image; that indication has no image.')
            continue
        images.filter(scan_id=key).delete()
        ReportImage.objects.create(report=report, kind=ReportImage.INDICATION, scan_id=key, image=upload)


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
    # ...and the weld form's technician and reviewer lines
    for row in Report.objects.order_by('pk').values_list('weld_technician', 'weld_technician_cert',
                                                          'weld_reviewer', 'weld_reviewer_cert'):
        for name, certification in (row[:2], row[2:]):
            if name.strip():
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
    # Guided mode (wizard.js): one section at a time, saved on each Prev / Next
    wizard = (request.POST if request.method == 'POST' else request.GET).get('wizard') == '1'
    wizard_step = (request.POST.get('wizard_step') if request.method == 'POST' else request.GET.get('step')) or ''

    if request.method == 'POST':
        # Bind to the loaded report (if any) so saving updates it instead of creating a copy
        instance = _get_report(request.POST.get('report_id'))
        if instance is not None and instance.is_issued:
            messages.error(request, ISSUED_MESSAGE)
            return redirect(f"{reverse('create-report')}?loaded={instance.pk}")

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
        # The weld form's equipment grid (only posted by editors that show it)
        probes, groups = equipment_formsets(request.POST, instance=form.instance) \
            if 'probes-TOTAL_FORMS' in request.POST else (None, None)
        formsets = tuple(fs for fs in (setup_formset, people, drawings, image_formset, probes, groups) if fs is not None)

        valid = form.is_valid() and all(fs.is_valid() for fs in formsets) and results_ok
        if valid:
            # Checked after the formsets so each file's error can be shown on its setup block
            setup_uploads = _setup_image_uploads(request, setup_formset)
            valid = not any(f.errors for f in setup_formset.forms)
        if valid:
            with transaction.atomic():
                report = form.save()
                # A new setup block holding only the report type's setup defaults isn't a setup
                _, setup_defaults = defaults_for(report.report_type)
                _save_ordered_formset(setup_formset, skip_new=lambda f: only_defaults(f, setup_defaults))
                _save_setup_images(request, report, setup_formset, setup_uploads)
                _save_ordered_formset(people)
                if probes is not None:
                    _save_equipment(report, probes, groups)
                _save_ordered_formset(drawings, kind=ReportImage.DRAWING)
                _save_ordered_formset(image_formset, kind=ReportImage.SCAN)
                if results is not None:
                    _save_results_table(report, *results)
                    _save_indication_images(request, report, results[1])

            if wizard:
                return _wizard_redirect(request, report, request.POST.get('wizard_goto', ''))
            if 'issue' in request.POST:
                _set_status(report, Report.ISSUED)
                messages.success(request, 'Report saved and issued. It is read-only until reopened.')
                return redirect(f"{reverse('create-report')}?loaded={report.pk}")
            wants_output = 'generate' in request.POST or 'preview' in request.POST
            if wants_output and not has_equipment(report):
                messages.success(request, 'Report saved.')
                messages.error(request, NEEDS_SETUP_MESSAGE)
                return redirect(f"{reverse('create-report')}?loaded={report.pk}")
            if 'preview' in request.POST:
                messages.success(request, 'Report saved.')
                return redirect('preview-report', pk=report.pk)
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
        if loaded_report is None:
            # A new report starts from its type's defaults (Preferences › Defaults): the type
            # picked under New report (?type=), else the default type
            report_type = request.GET.get('type')
            if report_type not in REPORT_TYPES:
                report_type = DEFAULT_REPORT_TYPE
            report_values, setup_values = defaults_for(report_type)
            form = ReportForm(initial={**report_values, 'report_type': report_type})
            setup_formset = SetupFormSet(initial=[setup_values])
        else:
            if wizard and loaded_report.is_issued:   # nothing to step through: shown read-only
                return redirect(f"{reverse('create-report')}?loaded={loaded_report.pk}")
            form = ReportForm(instance=loaded_report)
            setup_formset = SetupFormSet(instance=loaded_report)
            if loaded_report.setups.exists():
                setup_formset.extra = 0   # no blank block (its empty fields would count as still to fill)
        people = PersonFormSet(instance=loaded_report, prefix='people')
        probes, groups = equipment_formsets(instance=loaded_report)
        drawings = drawing_formset(instance=loaded_report)
        scan_ids = [scan_id for scan_id, _ in report_scan_rows(loaded_report)]
        image_formset = scan_image_formset(instance=loaded_report, scan_ids=scan_ids)
        if loaded_report is not None and hasattr(loaded_report, 'results_table'):
            columns, rows = report_results(loaded_report)
            results_data = {'columns': columns, 'rows': rows}

    saved_values = _saved_setup_values()
    return render(request, 'reports/create_report.html', {
        'form': form,
        'setup_formset': setup_formset,
        'person_formset': people,
        'probe_formset': probes if probes is not None else equipment_formsets(instance=form.instance)[0],
        'group_formset': groups if groups is not None else equipment_formsets(instance=form.instance)[1],
        'weld_grid': weld_grid_rows(),
        'sensitivity_blocks': library_blocks(),
        # How many results rows the weld form holds: page 1, then the Continuation page
        'indication_images': {image.scan_id: image.image.url for image in ReportImage.objects.filter(
            report_id=form.instance.pk, kind=ReportImage.INDICATION)} if form.instance.pk else {},
        'weld_results_rows': {'page1': len(REPORT_RESULT_ROWS), 'total': len(REPORT_RESULT_ROWS) + len(CONTINUATION_ROWS)},
        'has_equipment': bool(form.instance.pk) and has_equipment(form.instance),
        # What the Excel form leaves out of this report (its pages hold so much), and equipment
        # out of calibration on its test date
        'output_warnings': report_warnings(form.instance) if form.instance.pk else [],
        'drawing_formset': drawings,
        'image_formset': image_formset,
        'known_people': _known_people(),
        'results_data': results_data,
        'report_types': {key: t.as_json() for key, t in REPORT_TYPES.items()},
        'saved_setups': _saved_setup_choices(),
        'saved_setup_values': saved_values,
        # A setup without a file of its own is marked by its number (an import fills a column once)
        'saved_setup_columns': {pk: columns_from_setup(with_library_scope(
                                    {**values, 'source_file': values.get('source_file') or f'Setup #{pk}'})[0])
                                for pk, values in saved_values.items()},
        'report_defaults': all_defaults(),
        'pdf_available': pdf_available(form.instance if form.instance.pk else None),
        'excel': bool(form.instance.pk) and _is_excel(form.instance),
        'wizard': wizard and bool(form.instance.pk),
        'issued': form.instance.pk is not None and form.instance.is_issued,
        'wizard_step': wizard_step,
        'rtype': get_report_type(form.instance.report_type),
    })




ISSUED_MESSAGE = "This report is issued, so it can't be changed. Reopen it for editing first."


def _set_status(report, status):
    report.status = status
    if status == Report.ISSUED:
        report.issued_date = date.today()
    report.save(update_fields=['status', 'issued_date', 'updated_at'])


def report_status(request, pk):
    """POST action=issue / reopen: marks the report Issued (read-only) or back to Draft."""
    report = get_object_or_404(Report, pk=pk)
    action = request.POST.get('action') if request.method == 'POST' else None
    if action == 'issue':
        _set_status(report, Report.ISSUED)
        messages.success(request, 'Report issued. It is read-only until reopened.')
    elif action == 'reopen':
        _set_status(report, Report.DRAFT)
        messages.success(request, 'Report reopened for editing. Issue it again once it is re-sent.')
    target = request.POST.get('next', '')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(f"{reverse('create-report')}?loaded={report.pk}")


def _section_titles(report_type):
    """(section, title) for every section, with the type's own titles."""
    own = dict(get_report_type(report_type).labels)
    return [(key, own.get(f'section:{key}', title)) for key, title, _ in REPORT_SECTIONS]


def wizard_url(report, step=''):
    """The guided editor at this step (its first when blank)."""
    return f"{reverse('create-report')}?loaded={report.pk}&wizard=1" + (f'&step={step}' if step else '')


def _wizard_redirect(request, report, goto):
    """After a guided step saved: the step asked for, or the preview at the end."""
    if goto != 'finish':
        return redirect(wizard_url(report, re.sub(r'[^\w-]', '', goto)))
    if not has_equipment(report):
        messages.error(request, NEEDS_SETUP_MESSAGE)
        return redirect(wizard_url(report, get_report_type(report.report_type).wizard_equipment_step))
    return redirect(f"{reverse('preview-report', args=[report.pk])}?wizard=1")


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


NEEDS_SETUP_MESSAGE = 'Add at least one UT setup (or, on a weld report, a probe or group) before generating the report.'


def has_equipment(report):
    """A report can be generated once it has a setup, or a probe / group column on the weld form."""
    return report.setups.exists() or report.probes.exists() or report.groups.exists()


def _save_equipment(report, probes, groups):
    """
    Saves the weld form's probe and group columns in their order on the page (ORDER, which
    weld_grid.js keeps up to date as columns are moved); a group's probe is
    the probe column it chose (by its index in the probes formset, so it can be a new one).
    """
    def kept(formset):
        formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for f in in_page_order(formset):
            # A new column nobody filled in (its place on the page alone isn't a change) is skipped
            if f in formset.deleted_forms or (f.instance.pk is None and not set(f.changed_data) - {'ORDER'}):
                continue
            yield f

    by_index = {}
    for order, f in enumerate(kept(probes)):
        f.instance.report, f.instance.order = report, order
        # Wedge dia. is the pipe's: the item inspected's diameter (Sensitivity block & test material)
        diameter = wedge_diameter_for(f.instance.kind, report.item_diameter)
        if diameter is not None:
            f.instance.wedge_diameter = diameter
        f.instance.save()
        by_index[f.prefix.rsplit('-', 1)[1]] = f.instance
    for order, f in enumerate(kept(groups)):
        f.instance.report, f.instance.order = report, order
        column = f.cleaned_data.get('probe_column') or ''
        f.instance.not_applicable = column == NOT_USED
        f.instance.probe = by_index.get(column)
        f.instance.save()


def _report_with_setups(request, pk):
    """(report, None) when the report can be generated, else (report, the response saying why)."""
    report = get_object_or_404(Report, pk=pk)
    if not has_equipment(report):
        return report, _download_error(request, pk, NEEDS_SETUP_MESSAGE)
    return report, None


def _download_error(request, pk, message):
    """
    A file that couldn't be made. Download links are fetched by app.js (header X-Download: 1),
    which shows `message` on the page it was clicked from: answered as JSON, so the browser never
    saves an error page as the file. Anything else goes back to the editor with the message.
    """
    if request.headers.get('X-Download') == '1':
        return JsonResponse({'error': message}, status=409)
    messages.error(request, message)
    return redirect(f"{reverse('create-report')}?loaded={pk}")


def preview_report(request, pk):
    """
    Preview page: the browser renders the generated .docx (docx-preview) so layout, text and
    images can be checked before downloading
    """
    wizard = request.GET.get('wizard') == '1'
    report, redirect_response = _report_with_setups(request, pk)
    if redirect_response:
        return redirect(wizard_url(report, get_report_type(report.report_type).wizard_equipment_step)) \
            if wizard else redirect_response
    return render(request, 'reports/preview.html', {
        'report': report,
        'wizard': wizard,
        'wizard_prev': wizard_url(report, get_report_type(report.report_type).wizard_last_step),
        'wizard_prev_title': dict(_section_titles(report.report_type)).get(
            get_report_type(report.report_type).wizard_last_step, 'Scan plan'),
        # Files, Welds, the type's sections, the scan plan, this page
        'wizard_steps': get_report_type(report.report_type).wizard_step_count,
        'excel': _is_excel(report),
        'pdf_available': pdf_available(report),
    })


def _is_excel(report):
    return get_report_type(report.report_type).output_format == 'xlsx'


def pdf_available(report=None):
    """Whether a PDF can be made: by Excel for Excel report types, otherwise by Word."""
    return excel_available() if report is not None and _is_excel(report) else word_available()


def _excel_unavailable_message():
    return 'Excel reports need Microsoft Excel on the computer running this app.'


class ReportRenderError(Exception):
    """The Word report couldn't be made from its template."""


def _render_docx(report, **kwargs):
    """render_report, with any failure (e.g. a broken template) as a ReportRenderError to show."""
    try:
        return render_report(report, **kwargs)
    except Exception as e:
        logger.exception('Word report render failed')
        raise ReportRenderError(f'The Word report could not be made: {e}') from e


def report_docx(request, pk):
    """The generated .docx served inline for the preview page (no server copy is written)"""
    report, redirect_response = _report_with_setups(request, pk)
    if redirect_response:
        return redirect_response
    if _is_excel(report):  # no in-browser fallback for Excel reports
        return render(request, 'reports/pdf_error.html',
                      {'message': _excel_unavailable_message(), 'report': report, 'excel': True}, status=503)
    try:
        content = _render_docx(report)
    except ReportRenderError as e:
        return render(request, 'reports/pdf_error.html', {'message': str(e), 'report': report}, status=500)
    response = FileResponse(io.BytesIO(content), content_type=DOCX_CONTENT_TYPE,
                            filename=f'{safe_filename(report.document_filename)}.docx')
    response['Cache-Control'] = 'no-store'
    return response


def _save_to_job_folder(request, report, name, content):
    """
    Saves a download into the report's job folder as `name`. A file of that name the app didn't
    write for this report (e.g. a report made before the app) is kept: the copy is 'name (2)'
    instead. Only the app's own files are replaced.
    """
    folder = report.job_folder
    if not os.path.isdir(folder):
        messages.warning(request, f'The job folder {folder} is gone; the report was only downloaded.')
        return
    target, own = name, set(report.job_folder_files or [])
    stem, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(folder, target)) and target not in own:
        target, n = f'{stem} ({n}){ext}', n + 1
    try:
        with open(os.path.join(folder, target), 'wb') as f:
            f.write(content)
    except PermissionError:
        messages.warning(request, f"Couldn't save {target} into the job folder: is it open in Excel / Word / a PDF viewer? "
                                  'Close it and download again.')
        return
    if target not in own:
        report.job_folder_files = sorted(own | {target})
        Report.objects.filter(pk=report.pk).update(job_folder_files=report.job_folder_files)


def _save_copy(request, report, name, content):
    """A downloaded report also goes into its job folder, else (optionally) the server's outputs folder."""
    if report.job_folder:
        _save_to_job_folder(request, report, name, content)
    else:
        _save_server_copy(name, content)


def _save_server_copy(name, content):
    """Optionally keep a copy on the server (REPORT_OUTPUT_DIR = None turns this off)."""
    if not settings.REPORT_OUTPUT_DIR:
        return
    copy_path = os.path.join(settings.REPORT_OUTPUT_DIR, name)
    try:
        os.makedirs(settings.REPORT_OUTPUT_DIR, exist_ok=True)
        with open(copy_path, 'wb') as f:
            f.write(content)
    except PermissionError:
        # Usually the previous copy is open (Word / a PDF viewer); the download still works
        logger.warning('Could not update server copy %s (file in use?)', copy_path)


@xframe_options_sameorigin  # shown inside the app's own preview page; other sites still can't frame it
def report_pdf(request, pk):
    """
    The report as a PDF made by Word (or Excel, for Excel report types): inline for the preview
    page, or as a download with ?download=1 (which also keeps a server copy, like the .docx download)
    """
    report, redirect_response = _report_with_setups(request, pk)
    if redirect_response:
        return redirect_response
    download = request.GET.get('download') == '1'
    name = f'{safe_filename(report.document_filename)}.pdf'
    try:
        if _is_excel(report):
            if not excel_available():
                raise ExcelReportError(_excel_unavailable_message())
            _, pdf = build_workbook(report, pdf=True)
        else:
            if not word_available():
                raise WordPdfError('PDF output needs Microsoft Word on the computer running this app.')
            pdf = docx_to_pdf(_render_docx(report, update_fields_on_open=False))
    except (WordPdfError, ExcelReportError, ReportRenderError) as e:
        if download:
            return _download_error(request, pk, str(e))
        return render(request, 'reports/pdf_error.html',
                      {'message': str(e), 'report': report, 'excel': _is_excel(report)}, status=503)
    if download:
        _save_copy(request, report, name, pdf)
    response = FileResponse(io.BytesIO(pdf), as_attachment=download, filename=name, content_type='application/pdf')
    response['Cache-Control'] = 'no-store'
    return _with_warnings(response, report) if download else response


def generate_report(request, pk):
    """
    Renders the report's template (per report type) and returns it as a download: .docx for
    Word report types, .xlsx (filled by Excel) for Excel ones
    """
    report, redirect_response = _report_with_setups(request, pk)
    if redirect_response:
        return redirect_response

    if _is_excel(report):
        return _excel_download(request, report)

    output_name = f'{safe_filename(report.document_filename)}.docx'
    try:
        content = _render_docx(report)
    except ReportRenderError as e:
        return _download_error(request, report.pk, str(e))

    _save_copy(request, report, output_name, content)

    return _with_warnings(FileResponse(io.BytesIO(content), as_attachment=True, filename=output_name,
                                       content_type=DOCX_CONTENT_TYPE), report)


def _excel_download(request, report):
    output_name = f'{safe_filename(report.document_filename)}.xlsx'
    try:
        if not excel_available():
            raise ExcelReportError(_excel_unavailable_message())
        content, _ = build_workbook(report)
    except ExcelReportError as e:
        return _download_error(request, report.pk, str(e))
    _save_copy(request, report, output_name, content)
    return _with_warnings(FileResponse(io.BytesIO(content), as_attachment=True, filename=output_name,
                                       content_type=XLSX_CONTENT_TYPE), report)


def report_warnings(report):
    """What to warn about before the report goes out: what the Excel form leaves out, and equipment out of cal."""
    return output_warnings(report) + report_cal_warnings(report)


def _with_warnings(response, report):
    """The download with report_warnings in X-Report-Warnings, for app.js to show."""
    warnings = report_warnings(report)
    if warnings:
        response['X-Report-Warnings'] = json.dumps(warnings)   # ASCII (non-ASCII is escaped), as headers must be
    return response


@transaction.atomic
def _duplicate_report(original):
    """
    Start a repeat inspection from an earlier report: the copy keeps the report text,
    personnel, setups (with calibration screenshots), the weld form's probe and group columns and
    equipment drawings, but starts with no results, no scan images and no test dates. Images are
    shared with the original, not copied on disk; so is the scan plan, until a weld added to it
    makes the copy its own (add_weld_to_plan).
    """
    people = list(original.people.all())
    probes = list(original.probes.order_by('order', 'pk'))
    groups = list(original.groups.order_by('order', 'pk'))
    setups = list(original.setups.order_by('order').prefetch_related('images'))
    drawings = list(original.images.filter(kind=ReportImage.DRAWING).order_by('order'))

    report = Report.objects.get(pk=original.pk)
    report.pk = None
    report.document_filename = f'{original.document_filename or "Untitled"} (copy)'
    report.report_date = date.today()   # as a new report in the editor; the test dates are the new job's
    report.test_date = report.test_end_date = None
    report.status, report.issued_date = Report.DRAFT, None   # a new report: not sent yet
    # A repeat inspection is a new job: it gets its own folder (if any), never the original's files
    report.job_folder, report.job_folder_files = '', []
    report.save()

    for person in people:
        person.pk, person.report = None, report
        person.save()
    for setup in setups:
        images = list(setup.images.all())
        setup.pk, setup.report = None, report
        setup.save()
        for image in images:
            image.pk, image.setup = None, setup
            image.save()
    new_probes = {}
    for probe in probes:
        old_pk = probe.pk
        probe.pk, probe.report = None, report
        probe.save()
        new_probes[old_pk] = probe
    for group in groups:
        group.pk, group.report = None, report
        group.probe = new_probes.get(group.probe_id)
        group.save()
    for drawing in drawings:
        drawing.pk, drawing.report = None, report
        drawing.save()
    return report


def report_list(request):
    """
    View all report information stored within the database
    """
    reports = Report.objects.annotate(
        setup_count=Count('setups', distinct=True), probe_count=Count('probes', distinct=True),
        group_count=Count('groups', distinct=True),
    ).prefetch_related('people').order_by('-pk')
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            # Issued reports are kept: they were sent, so deleting one takes reopening it first
            selected = Report.objects.filter(pk__in=selected_pks)
            kept = selected.filter(status=Report.ISSUED).count()
            drafts = selected.exclude(status=Report.ISSUED)
            count = drafts.count()
            drafts.delete()
            if count:
                messages.success(request, f"Deleted {count} report{'s' if count != 1 else ''}.")
            if kept:
                messages.warning(request, f"{kept} issued report{'s were' if kept != 1 else ' was'} kept: "
                                          'reopen a report in the editor to delete it.')
            return redirect('report-list')
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            duplicate = _duplicate_report(get_object_or_404(Report, pk=selected_pks[0]))
            messages.success(request, 'Report duplicated. Results, scan images and dates start empty.')
            return redirect(f"{reverse('create-report')}?loaded={duplicate.pk}")
    word_ok, excel_ok = word_available(), excel_available()
    reports = list(reports)
    for report in reports:
        report.type_label = get_report_type(report.report_type).label
        report.client_key = report.client.strip()   # the client filter's value
        report.is_excel = _is_excel(report)
        report.pdf_ok = excel_ok if report.is_excel else word_ok
        # As has_equipment(): a setup, or a probe / group column on the weld form
        report.can_generate = bool(report.setup_count or report.probe_count or report.group_count)
    return render(request, 'reports/report_list.html', {
        'items': reports,
        # The list's filters: every type, and the clients on the reports
        'type_choices': [(key, t.label) for key, t in REPORT_TYPES.items()],
        'clients': sorted({r.client.strip() for r in reports if r.client.strip()}, key=str.lower),
    })


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
