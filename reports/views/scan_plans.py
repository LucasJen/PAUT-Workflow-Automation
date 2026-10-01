import math
import re

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from equipment.compat import wedges_for_probe
from equipment.models import ProbeModel, SensitivityBlock, WedgeModel

from ..forms import ScanPlanForm
from ..models import ScanPlan, Setup
from ..services.scan_plan import (
    M_PER_S_TO_IN_PER_US, MM_PER_IN, STEEL_LONGITUDINAL, STEEL_SHEAR, render_png,
)

NUMBER = re.compile(r'-?\d+(?:\.\d+)?')


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
    {pk: {label, field: value}} for filling a scan plan from a saved setup in the browser. Lengths
    are in inches whatever the setup's units; the page converts them for a metric plan.
    """
    values = {}
    for setup in Setup.objects.order_by('report_id', '-pk'):
        angles = [float(n) for n in NUMBER.findall(setup.angle_range or '')]
        per_inch = MM_PER_IN if setup.units == 'metric' else 1.0

        def length(text):
            value = _first_number(text)
            return round(value / per_inch, 4) if value is not None else None

        fill = {
            'thickness': length(setup.specimen_thickness),
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
        fill = {k: v for k, v in fill.items() if v is not None}
        if fill:
            label = ' · '.join(filter(None, [setup.title, setup.transducer_model, setup.angle_range]))
            where = f'report #{setup.report_id}' if setup.report_id else 'saved'
            values[setup.pk] = {'label': f'{label or "Setup"} ({where} #{setup.pk})', 'fields': fill}
    return values


def _block_fill_values():
    """{pk: {field: value}} filled into a scan plan when its sensitivity block is picked."""
    values = {}
    for block in SensitivityBlock.objects.all():
        fill = {
            'pipe_size': block.pipe_size,
            'thickness': _first_number(block.test_thickness) or _first_number(block.cal_thickness),
            'bevel_angle': _first_number(block.bevel_geometry),
            'shear_velocity': _first_number(block.velocity_shear),
        }
        values[block.pk] = {k: v for k, v in fill.items() if v not in (None, '')}
    return values


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


def _wedge_fill_values():
    """{pk: {field: value}} the wedge selector fills in (wedge angle and exit point are hidden fields)."""
    values = {}
    for wedge in WedgeModel.objects.all():
        fill = {'wedge_angle': wedge.wedge_angle, 'exit_point': _wedge_exit_point(wedge)}
        fill = {k: v for k, v in fill.items() if v is not None}
        if fill:
            values[wedge.pk] = fill
    return values


def _edit_page(request, form, plan):
    return render(request, 'reports/edit_scan_plan.html', {
        'form': form, 'plan': plan, 'setup_fill_values': _setup_fill_values(),
        'catalogue_fill_values': {
            'sensitivity_block': _block_fill_values(),
            'wedge_model': _wedge_fill_values(),
        },
    })


def new_scan_plan(request):
    """
    New scan plan, with the live drawing shown while it is filled in
    """
    if request.method == 'POST' and 'delete' in request.POST:  # 'Delete' on an unsaved plan = discard
        return redirect('scan-plan-list')
    form = ScanPlanForm(request.POST or None)
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


def scan_plan_preview(request):
    """
    The drawing for the values currently in the form (not saved), for the live preview
    """
    data = request.GET.copy()
    if not data.get('name'):
        data['name'] = 'preview'  # a name is only needed to save
    form = ScanPlanForm(data)
    if not form.is_valid():
        return HttpResponse('Check the highlighted values.', status=400, content_type='text/plain')
    return _png(render_png(form.save(commit=False), _side(request)))


def scan_plan_png(request, pk):
    """The saved scan plan's drawing (?side=2 for the other side)"""
    return _png(render_png(get_object_or_404(ScanPlan, pk=pk), _side(request)))


def scan_plan_wedges(request):
    """[[pk, name], ...] of the wedges that fit ?probe=<pk>, for the scan plan's wedge list"""
    probe = ProbeModel.objects.filter(pk=request.GET.get('probe') or None).first()         if (request.GET.get('probe') or '').isdigit() else None
    wedges = wedges_for_probe(probe, WedgeModel.objects.all()) if probe else []
    return JsonResponse({'wedges': [[w.pk, str(w)] for w in wedges]})
