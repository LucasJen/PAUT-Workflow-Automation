import math
import re

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from equipment.compat import wedges_for_probe
from equipment.models import ProbeModel, SensitivityBlock, WedgeModel

from ..forms import ScanPlanForm
from ..models import Report, ReportGroup, ScanPlan, Setup
from ..weld_form import PAUT
from ..services.scan_plan import (
    M_PER_S_TO_IN_PER_US, MM_PER_IN, STEEL_LONGITUDINAL, STEEL_SHEAR, build_scene, coverage, layout,
    render_png, suggest_offset, toe,
)
from ..services.scan_plan.beams import LIFT_OFF_WARNING, fan as beam_fan
from ..services.scan_plan.coverage import drawings as plan_drawings
from ..services.scan_plan import reflectors as reflector_kinds
from ..services.scan_plan.geometry import outside_diameter
from ..services.scan_plan.render import COLOURS, WIDTH_PX

NUMBER = re.compile(r'-?\d+(?:\.\d+)?')
# In a range such as '40-70', a dash straight after a number separates; it isn't a minus sign
RANGE_NUMBER = re.compile(r'(?<![\d.°])-?\d+(?:\.\d+)?')


def scan_plan_list(request):
    """
    Saved scan plans, picked from the report editor for weld reports
    """
    plans = ScanPlan.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            ScanPlan.objects.filter(pk__in=selected_pks).delete()
            return redirect('scan-plan-list')
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(ScanPlan, pk=selected_pks[0])
            original.pk = None
            original.name = f'{original.name} (copy)'
            original.save()
            return redirect('scan-plan-list')
    return render(request, 'reports/scan_plan_list.html', {'items': plans})


def _first_number(text):
    match = NUMBER.search(text or '')
    return float(match.group()) if match else None


def _setup_fill_values():
    """
    {pk: {label, fields, wedge_geometry, name, block}} for filling a scan plan from a saved setup in
    the browser, with its report's sensitivity block (which gives the thickness). Lengths are in
    inches whatever the setup's units; the page converts them for a metric plan.
    """
    values = {}
    for setup in Setup.objects.select_related('report__sensitivity_block').order_by('report_id', '-pk'):
        angles = [float(n) for n in RANGE_NUMBER.findall(setup.angle_range or '')]
        per_inch = MM_PER_IN if setup.units == 'metric' else 1.0

        def length(text):
            value = _first_number(text)
            return round(value / per_inch, 4) if value is not None else None

        # Thickness comes from the report's sensitivity block, not the setup
        fill = {
            'index_offset': length(setup.index_offset),
            'bevel_angle': _first_number(setup.weld_bevel_angle),
            'root_face': length(setup.weld_root_face),
            'root_gap': length(setup.weld_root_gap),
            'cap_width': length(setup.weld_cap_width) or '',  # blank: calculated from the bevel
            'angle_start': angles[0] if angles else None,
            'angle_stop': angles[-1] if angles else None,
            'angle_step': _first_number(setup.angle_step),
            'probe_model': setup.catalogue_probe_id,
            'wedge_model': setup.catalogue_wedge_id,
            'first_element': setup.first_element,
            'aperture_elements': setup.aperture_elements,
        }
        fill, block = _with_report_block({k: v for k, v in fill.items() if v is not None}, setup.report)
        # The wedge geometry the .nde recorded: applied after the wedge is picked (scan_plan.js)
        geometry = {
            'wedge_primary_offset': setup.wedge_primary_offset,
            'wedge_first_element_height': setup.wedge_first_element_height,
            'wedge_velocity': setup.wedge_velocity,
            'wedge_length': setup.wedge_length,
            'wedge_height': setup.wedge_height,
            'wedge_angle': _first_number(setup.wedge_angle),
        }
        geometry = geometry if setup.wedge_primary_offset is not None else {}
        if fill or geometry:
            label = ' · '.join(filter(None, [setup.title, setup.transducer_model, setup.angle_range]))
            where = f'report #{setup.report_id}' if setup.report_id else 'saved'
            values[setup.pk] = {'label': f'{label or "Setup"} ({where} #{setup.pk})', 'fields': fill,
                                'wedge_geometry': {k: v for k, v in geometry.items() if v is not None},
                                'name': (setup.title or label or f'Setup {setup.pk}')[:100],
                                'block': str(block) if block else None,
                                'has_report': setup.report_id is not None}
    return values


def group_fill(group):
    """
    (fields, wedge geometry) a scan plan takes from a weld report's group column: its angles and
    aperture, and its probe column's catalogue probe / wedge and .nde wedge geometry.
    """
    probe = group.probe
    angles = [float(n) for n in RANGE_NUMBER.findall(group.angles or '')]
    fill = {
        'angle_start': angles[0] if angles else None,
        'angle_stop': angles[-1] if angles else None,
        'angle_step': _first_number(group.angle_increment),
        'first_element': group.first_element,
        'aperture_elements': group.aperture_elements,
        'probe_model': probe.catalogue_probe_id if probe else None,
        'wedge_model': probe.catalogue_wedge_id if probe else None,
    }
    geometry = {}
    if probe is not None and probe.wedge_primary_offset is not None:
        geometry = {
            'wedge_primary_offset': probe.wedge_primary_offset,
            'wedge_first_element_height': probe.wedge_first_element_height,
            'wedge_velocity': probe.wedge_velocity,
            'wedge_length': probe.wedge_length,
            'wedge_height': probe.wedge_height,
            'wedge_angle': _first_number(probe.wedge_angle),
        }
    return ({k: v for k, v in fill.items() if v is not None},
            {k: v for k, v in geometry.items() if v is not None})


def _group_fill_values():
    """
    {'g<pk>': {label, fields, wedge_geometry, name, block}} for filling a scan plan from a weld
    report's group column (group_fill), with the report's sensitivity block (thickness, bevel).
    """
    values = {}
    groups = ReportGroup.objects.select_related('probe', 'report__sensitivity_block').order_by('-report_id', 'order')
    for group in groups:
        if group.not_applicable or (group.probe is not None and group.probe.kind != PAUT):
            continue   # a scan plan is a phased-array sectorial scan
        fill, geometry = group_fill(group)
        if not (fill or geometry):
            continue
        fill, block = _with_report_block(fill, group.report)
        probe, report = group.probe, group.report
        name = report.document_filename or f'Report #{report.pk}'
        column = f'Group {group.order + 1}' + (f' ({group.label})' if group.label else '')
        label = ' · '.join(filter(None, [name, column, probe.model if probe else '', group.angles]))
        values[f'g{group.pk}'] = {'label': label, 'fields': fill, 'wedge_geometry': geometry, 'name': name[:100],
                                  'block': str(block) if block else None, 'has_report': True}
    return values


def _block_fill(block):
    """{field: value} a scan plan takes from a sensitivity block: the plan's thickness comes from here."""
    fill = {
        'pipe_size': block.pipe_size,
        'thickness': _first_number(block.test_thickness) or _first_number(block.cal_thickness),
        'outside_diameter': _first_number(block.test_diameter) or _first_number(block.cal_diameter),
        'bevel_angle': _first_number(block.bevel_geometry),
        'shear_velocity': _first_number(block.velocity_shear),
    }
    return {k: v for k, v in fill.items() if v not in (None, '')}


def _block_fill_values():
    """{pk: {field: value}} filled into a scan plan when its sensitivity block is picked."""
    return {block.pk: _block_fill(block) for block in SensitivityBlock.objects.all()}


def _with_report_block(fill, report):
    """
    `fill` with the report's sensitivity block picked and its values under the source's own
    (so a setup's bevel from its .nde wins over the block's); the block's thickness always wins.
    Returns (fill, block or None).
    """
    block = report.sensitivity_block if report is not None else None
    if block is None:
        return fill, None
    from_block = _block_fill(block)
    fill = {'sensitivity_block': block.pk, **from_block, **fill}
    if 'thickness' in from_block:
        fill['thickness'] = from_block['thickness']
    return fill, block


def _wedge_exit_point(wedge):
    """
    Wedge front to where the wedge's nominal beam leaves it, in inches, from the first element
    (the scan plan works out each beam's own exit point when it draws; this is the plan's
    single exit point for when it can't).
    """
    if not wedge.has_geometry:
        return None
    refracted = wedge.refracted_angle if wedge.refracted_angle is not None else 60.0
    part = STEEL_LONGITUDINAL if wedge.wave_type == 'LW' else STEEL_SHEAR
    sin_i = wedge.velocity * M_PER_S_TO_IN_PER_US / part * math.sin(math.radians(refracted))
    if sin_i >= 1:
        return None
    behind_front_mm = -wedge.primary_offset - wedge.first_element_height * math.tan(math.asin(sin_i))
    return round(max(behind_front_mm, 0.0) / MM_PER_IN, 3)


def _wedge_fill(wedge):
    """The wedge angle and exit point a scan plan takes from a catalogue wedge."""
    fill = {'wedge_angle': wedge.wedge_angle, 'exit_point': _wedge_exit_point(wedge)}
    return {k: v for k, v in fill.items() if v is not None}


def _wedge_fill_values():
    """{pk: {field: value}} the wedge selector fills in (wedge angle and exit point are hidden fields)."""
    values = {}
    for wedge in WedgeModel.objects.all():
        fill = _wedge_fill(wedge)
        # Picking a wedge drops any .nde geometry from a setup (it belonged to that setup's wedge)
        values[wedge.pk] = {**fill, 'wedge_primary_offset': '', 'wedge_first_element_height': '',
                            'wedge_velocity': '', 'wedge_length': '', 'wedge_height': ''}
    return values


def _edit_page(request, form, plan):
    return render(request, 'reports/edit_scan_plan.html', {
        'form': form, 'plan': plan, 'setup_fill_values': _setup_fill_values(),
        'group_fill_values': _group_fill_values(),
        'advanced_fields': list(ScanPlanForm.ADVANCED_FIELDS),
        'reflector_kinds': reflector_kinds.KINDS, 'reflector_uses': reflector_kinds.USES,
        'catalogue_fill_values': {
            'sensitivity_block': _block_fill_values(),
            'wedge_model': _wedge_fill_values(),
        },
    })


# A new plan opens with one drawing to start from: a 1/2" flat plate (axial beams) with the
# model's standard single V (37.5 deg bevel, 1/16" gap and land, cap from the bevel), 90 deg skew only
NEW_PLAN_START = {'thickness': 0.5, 'skew_90': True, 'skew_270': False}


def new_scan_plan(request):
    """
    New scan plan, with the live drawing shown while it is filled in
    """
    if request.method == 'POST' and 'delete' in request.POST:  # 'Delete' on an unsaved plan = discard
        return redirect('scan-plan-list')
    form = ScanPlanForm(request.POST or None, initial=None if request.method == 'POST' else NEW_PLAN_START)
    if request.method == 'POST' and form.is_valid():
        plan = form.save()
        messages.success(request, f'Scan plan "{plan.name}" saved.')
        return redirect('edit-scan-plan', pk=plan.pk)
    return _edit_page(request, form, None)


def edit_scan_plan(request, pk):
    plan = get_object_or_404(ScanPlan, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            plan.delete()
            messages.success(request, 'Scan plan deleted.')
            return redirect('scan-plan-list')
        form = ScanPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, 'Scan plan saved.')
            return redirect('edit-scan-plan', pk=plan.pk)
    else:
        form = ScanPlanForm(instance=plan)
    return _edit_page(request, form, plan)


def _png(content):
    response = HttpResponse(content, content_type='image/png')
    response['Cache-Control'] = 'no-store'
    return response


def _side(request):
    return 2 if request.GET.get('side') == '2' else 1


def _position(request):
    return 2 if request.GET.get('position') == '2' else 1


def _plan_or_errors(request):
    """
    (plan, None): the scan plan the form's current values describe (not saved); or (None, the
    400 response naming the fields that stop it being drawn, for the editor to mark).
    """
    data = request.GET.copy()
    if not data.get('name'):
        data['name'] = 'preview'  # a name is only needed to save
    form = ScanPlanForm(data)
    if form.is_valid():
        return form.save(commit=False), None
    fields = {name: {'label': str(form.fields[name].label) if name in form.fields else '', 'errors': list(errors)}
              for name, errors in form.errors.items()}
    return None, JsonResponse({'error': 'Check the highlighted values.', 'fields': fields}, status=400)


def _coverage_json(plan):
    result = coverage(plan)
    return {
        'fraction': result.fraction, 'full': result.full, 'haz_width': plan.haz_width,
        'drawings': [{'position': position, 'side': side, 'fraction': fraction}
                     for (position, side), fraction in result.by_drawing.items()],
    }


def _pipe_json(plan):
    """
    For circumferential beams round a pipe: the OD drawn, the refracted angles the beams really
    enter at (against the nominal range) and a flat wedge's lift-off. None for a flat section.
    """
    od = outside_diameter(plan)
    if od is None:
        return None
    beams = beam_fan(plan)
    refracted = [t.refracted for t in beams.traces if t.refracted is not None]
    return {
        'od': od, 'contoured': plan.wedge_contour == ScanPlan.CONTOURED_WEDGE,
        'refracted': [min(refracted), max(refracted)] if refracted else None,
        'nominal': [min(plan.angle_start, plan.angle_stop), max(plan.angle_start, plan.angle_stop)],
        'lift_off': beams.lift_off, 'lift_off_warning': (beams.lift_off or 0) > LIFT_OFF_WARNING,
    }


def _rounded(value):
    """`value` with its floats to 5 places (a hundred-thousandth of an inch is plenty to draw)."""
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return value


def scan_plan_scenes(request):
    """
    Everything the editor's interactive drawing needs for the form's current values: one scene
    per ticked skew per index offset (with the coverage marks), the coverage and the wedge numbers
    """
    plan, errors = _plan_or_errors(request)
    if plan is None:
        return errors
    return JsonResponse({
        'drawings': [_rounded(build_scene(plan, side, position, analysis=True).as_dict())
                     for position, side in plan_drawings(plan)],
        'coverage': _coverage_json(plan), 'wedge': layout(plan).wedge_data, 'pipe': _pipe_json(plan),
        'colours': {name: '#%02x%02x%02x' % rgb for name, rgb in COLOURS.items()}, 'width_px': WIDTH_PX,
    })


def scan_plan_suggest(request):
    """
    The index offset (inches) that covers the most of the weld + HAZ for the form's current values,
    and a second offset when one can't cover it all
    """
    plan, errors = _plan_or_errors(request)
    if plan is None:
        return errors
    suggestion = suggest_offset(plan)
    return JsonResponse({
        'offset': suggestion.offset, 'low': suggestion.low, 'high': suggestion.high,
        'fraction': suggestion.fraction, 'second_offset': suggestion.second_offset,
        'pair_fraction': suggestion.pair_fraction, 'toe': toe(plan),
    })


def scan_plan_png(request, pk):
    """The saved scan plan's drawing (?side=2 for the 270 deg skew, ?position=2 for the second offset)"""
    return _png(render_png(get_object_or_404(ScanPlan, pk=pk), _side(request), _position(request)))


def scan_plan_wedges(request):
    """[[pk, name], ...] of the wedges that fit ?probe=<pk>, for the scan plan's wedge list"""
    probe = ProbeModel.objects.filter(pk=request.GET.get('probe') or None).first()         if (request.GET.get('probe') or '').isdigit() else None
    wedges = wedges_for_probe(probe, WedgeModel.objects.all()) if probe else []
    return JsonResponse({'wedges': [[w.pk, str(w)] for w in wedges]})


# ── A weld report's weld → its scan plan ─────────────────────────────────

OFFSET_TOLERANCE = 0.001   # inches: offsets this close are the same offset (one image per skew)


# A weld's C/L Offset cell: one offset, or several ('0.500 / 0.875'); always positive
OFFSET_NUMBER = re.compile(r'\d*\.?\d+')


def weld_offsets(text):
    """'0.500 / 0.875' -> [0.5, 0.875]; '' -> []."""
    return [float(n) for n in OFFSET_NUMBER.findall(text or '')]


def plan_drawing_views(report):
    """
    The report's scan plan drawings for the guided editor: [{'position', 'side', 'label', 'welds'}]
    per ticked skew per index offset, with the welds whose C/L offset is that offset.
    """
    from ..report_types import WELD_RESULTS_COLUMNS
    from ..results import report_results
    plan = report.scan_plan
    if plan is None:
        return []
    headings = dict(WELD_RESULTS_COLUMNS)
    columns, rows = report_results(report) if report.pk else ([], [])
    weld_at, offset_at = (columns.index(headings[key]) if headings[key] in columns else None
                          for key in ('weld_id', 'cl_offset'))
    welds = []   # [(weld ID, [offsets])]: a row with no Weld ID may be a further offset of the weld above
    if weld_at is not None and offset_at is not None:
        for cells in rows:
            cells = list(cells) + [''] * len(columns)
            if str(cells[weld_at]).strip():
                welds.append((str(cells[weld_at]).strip(), []))
            if welds:
                welds[-1][1].extend(weld_offsets(str(cells[offset_at])))
    views = []
    for position, side, label in plan.drawing_labels:
        offset = plan.index_offset if position == 1 else plan.index_offset_2
        views.append({'position': position, 'side': side, 'label': label,
                      'welds': [weld for weld, offsets in welds
                                if any(_same_offset(offset, o) for o in offsets)]})
    return views


def _weld_skews(location):
    """Probe 1 Location -> the skews it scans: '90/270' both, '90' or '270' one; no number, both."""
    numbers = {int(float(n)) for n in NUMBER.findall(location or '')}
    skews = {skew for skew in (90, 270) if skew in numbers}
    return skews or {90, 270}


def _same_offset(a, b):
    return (a is None and b is None) or (a is not None and b is not None and abs(a - b) < OFFSET_TOLERANCE)


def _inches(value):
    return f'{value:.3f}"' if value is not None else 'the weld toe'


def _new_plan_from_weld(report, thickness, cap_width, offset, skews):
    """A scan plan for the report from a weld, with the probe / wedge / angles of its first PAUT group."""
    plan = ScanPlan(name=(report.document_filename or f'Report #{report.pk}')[:100], thickness=thickness,
                    cap_width=cap_width, index_offset=offset, skew_90=90 in skews, skew_270=270 in skews)
    group = next((g for g in report.groups.select_related('probe')
                  if not g.not_applicable and g.probe is not None and g.probe.kind == PAUT), None)
    if group is not None:
        fill, geometry = group_fill(group)
        for name, value in fill.items():
            setattr(plan, f'{name}_id' if name in ('probe_model', 'wedge_model') else name, value)
        wedge = WedgeModel.objects.filter(pk=fill.get('wedge_model')).first() if fill.get('wedge_model') else None
        if wedge is not None:   # as picking the wedge on the scan plan page does
            for name, value in _wedge_fill(wedge).items():
                setattr(plan, name, value)
        for name, value in geometry.items():
            setattr(plan, name, value)
    plan.save()
    return plan, group


def _plan_json(plan):
    return {'pk': plan.pk, 'name': plan.name, 'url': reverse('edit-scan-plan', args=[plan.pk])}


def _own_plan(report, plan):
    """
    The plan to change for this report: itself when only this report uses it, else (unsaved
    changes and all) a new copy for this report, so other reports' scan plan pages stay as they were.
    """
    if not plan.reports.exclude(pk=report.pk).exists():
        return plan
    plan.pk = None
    plan.name = f'{plan.name} (report #{report.pk})'[:100]
    plan.save()
    report.scan_plan = plan
    report.save(update_fields=['scan_plan'])
    return plan


def add_weld_to_plan(report, thickness, cap_width, offset, skews):
    """
    Adds a weld to the report's scan plan: thickness, cap width, C/L offset (wedge front to the
    weld centre line) and skews. The first weld creates the plan (probe, wedge and angles from
    the report's first PAUT group); later welds add only what isn't in it yet: a skew not yet
    drawn for the same offset, or a second offset. Returns (ok, message, plan or None).
    """
    skew_text = ' and '.join(f'{s}°' for s in sorted(skews))
    plan = report.scan_plan
    if plan is None:
        if thickness is None:
            return False, 'Enter Probe 1 Thickness first.', None
        plan, group = _new_plan_from_weld(report, thickness, cap_width, offset, skews)
        report.scan_plan = plan
        report.save(update_fields=['scan_plan'])
        source = (f' with the probe and angles of Group {group.order + 1}' if group is not None
                  else '; pick its probe and wedge there (the report has no PAUT group)')
        return True, f'Made scan plan "{plan.name}" at offset {_inches(offset)} ({skew_text}){source}.', plan

    warnings = []
    if thickness is not None and abs(thickness - plan.thickness) >= OFFSET_TOLERANCE:
        warnings.append(f'Thickness {thickness:.3f}" differs from the plan\'s {plan.thickness:.3f}".')
    if cap_width is not None and plan.cap_width is not None and abs(cap_width - plan.cap_width) >= OFFSET_TOLERANCE:
        warnings.append(f'Weld width {cap_width:.3f}" differs from the plan\'s {plan.cap_width:.3f}".')

    second_free = plan.index_offset_2 is None and not (plan.skew_90_2 or plan.skew_270_2)
    if _same_offset(offset, plan.index_offset):
        fields = {90: 'skew_90', 270: 'skew_270'}
    elif not second_free and _same_offset(offset, plan.index_offset_2):
        fields = {90: 'skew_90_2', 270: 'skew_270_2'}
    elif second_free and offset is not None:
        plan.index_offset_2 = offset
        fields = {90: 'skew_90_2', 270: 'skew_270_2'}
    else:
        return False, (f'Scan plan "{plan.name}" already has two offsets ({_inches(plan.index_offset)} and '
                       f'{_inches(plan.index_offset_2)}); offset {_inches(offset)} wasn\'t added.'), plan

    added = sorted(skew for skew in skews if not getattr(plan, fields[skew]))
    if added:
        for skew in added:
            setattr(plan, fields[skew], True)
        plan = _own_plan(report, plan)
        plan.save()
        message = f'Added offset {_inches(offset)} ({", ".join(f"{s}°" for s in added)}) to scan plan "{plan.name}".'
    else:
        message = f'Offset {_inches(offset)} with {skew_text} is already in scan plan "{plan.name}"; nothing added.'
    return True, ' '.join([message, *warnings]), plan


@require_POST
def scan_plan_from_weld(request):
    """The weld report's Scan plan button: add_weld_to_plan for one weld's row. JSON {ok, message, plan}."""
    report_id = request.POST.get('report_id') or ''
    report = Report.objects.filter(pk=report_id).first() if report_id.isdigit() else None
    if report is None:
        return JsonResponse({'ok': False, 'message': 'Save the report first.'})
    if report.is_issued:
        return JsonResponse({'ok': False, 'message': 'The report is issued: reopen it to change its scan plan.'})
    # Each of the weld's offsets ('0.500 / 0.875'), or the weld toe when none is typed
    oks, messages_, plan = [], [], None
    for offset in weld_offsets(request.POST.get('cl_offset')) or [None]:
        ok, message, plan = add_weld_to_plan(
            report, _first_number(request.POST.get('probe1_thk')), _first_number(request.POST.get('weld_width')),
            offset, _weld_skews(request.POST.get('probe1_location')))
        report.refresh_from_db(fields=['scan_plan'])   # the next offset goes into the plan just made
        oks.append(ok)
        messages_.append(message)
    return JsonResponse({'ok': all(oks), 'message': ' '.join(messages_), **({'plan': _plan_json(plan)} if plan else {})})
