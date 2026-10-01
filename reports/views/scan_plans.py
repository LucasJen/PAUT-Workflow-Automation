import re

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from equipment.models import ProbeModel, SensitivityBlock, WedgeModel

from ..forms import ScanPlanForm
from ..models import ScanPlan, Setup
from ..services.scan_plan import render_png

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
    """{pk: {label, field: value}} for filling a scan plan from a saved setup in the browser."""
    values = {}
    for setup in Setup.objects.order_by('report_id', '-pk'):
        angles = [float(n) for n in NUMBER.findall(setup.angle_range or '')]
        fill = {
            'thickness': _first_number(setup.specimen_thickness),
            'wedge_angle': _first_number(setup.wedge_angle),
            'angle_start': angles[0] if angles else None,
            'angle_stop': angles[-1] if angles else None,
            'angle_step': _first_number(setup.angle_step),
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


def _wedge_fill_values():
    return {w.pk: {'wedge_angle': w.wedge_angle} for w in WedgeModel.objects.exclude(wedge_angle=None)}


def _edit_page(request, form, plan):
    return render(request, 'reports/edit_scan_plan.html', {
        'form': form, 'plan': plan, 'setup_fill_values': _setup_fill_values(),
        'catalogue_series': {
            'probes': dict(ProbeModel.objects.values_list('pk', 'series')),
            'wedges': dict(WedgeModel.objects.values_list('pk', 'probe_series')),
        },
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
    data.setdefault('name', 'preview')
    form = ScanPlanForm(data)
    if not form.is_valid():
        return HttpResponse('Check the highlighted values.', status=400, content_type='text/plain')
    return _png(render_png(form.save(commit=False), _side(request)))


def scan_plan_png(request, pk):
    """The saved scan plan's drawing (?side=2 for the other side)"""
    return _png(render_png(get_object_or_404(ScanPlan, pk=pk), _side(request)))
