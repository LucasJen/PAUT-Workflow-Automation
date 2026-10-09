import json

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import VesselForm
from ..models import Vessel
from ..services.vessel import (
    COMPASS, VesselSpec, build_scene, clean_coverage, render_png, side_names, spec_from, vessel_parts,
)
from ..services.vessel.render import COLOURS

# What a new vessel of each type starts as (vessel.js applies it when the type changes on a new
# vessel): its heads, and its rows from the start end (lengths in inches)
TYPE_STARTS = {
    Vessel.HORIZONTAL: {'start_head': 'ellipsoidal', 'end_head': 'ellipsoidal', 'diameter': 60,
                        'courses': [{'kind': 'course', 'length': 60}] * 3},
    Vessel.VERTICAL: {'start_head': 'ellipsoidal', 'end_head': 'ellipsoidal', 'diameter': 72,
                      'courses': [{'kind': 'course', 'length': 96}] * 5},
    Vessel.EXCHANGER: {'start_head': 'flat', 'end_head': 'ellipsoidal', 'diameter': 30,
                       'courses': [{'kind': 'flange'}, {'kind': 'course', 'length': 36, 'label': 'Channel'},
                                   {'kind': 'flange'}, {'kind': 'course', 'length': 96},
                                   {'kind': 'course', 'length': 96}]},
    Vessel.TANK: {'start_head': 'flat', 'end_head': 'cone', 'diameter': 600,
                  'courses': [{'kind': 'course', 'length': 96}] * 4},
}
NEW_VESSEL = {'vessel_type': Vessel.HORIZONTAL, 'diameter': 60, 'courses': TYPE_STARTS[Vessel.HORIZONTAL]['courses'],
              'nozzles': [], 'view_from': 'S'}


def vessel_list(request):
    """
    Saved vessel drawings, picked from a report's editor to mark its scan coverage
    """
    vessels = Vessel.objects.all()
    if request.method == 'POST':
        selected_pks = request.POST.getlist('selected')
        if 'delete' in request.POST:
            Vessel.objects.filter(pk__in=selected_pks).delete()
            return redirect('vessel-list')
        if 'duplicate' in request.POST and len(selected_pks) == 1:
            original = get_object_or_404(Vessel, pk=selected_pks[0])
            original.pk = None
            original.name = f'{original.name} (copy)'
            original.save()
            return redirect('vessel-list')
    return render(request, 'reports/vessel_list.html', {'items': vessels})


def _directions():
    """The nozzle directions each way a vessel can be seen offers, for vessel.js's direction lists."""
    horizontal = {}
    for view_from in COMPASS:
        near, far = side_names(VesselSpec(vessel_type=Vessel.HORIZONTAL, view_from=view_from))
        horizontal[view_from] = ['Top', near, 'Bottom', far]
    return {'horizontal': horizontal, 'compass': COMPASS}


def _edit_page(request, form, vessel):
    return render(request, 'reports/edit_vessel.html', {
        'form': form, 'vessel': vessel, 'type_starts': TYPE_STARTS, 'directions': _directions(),
    })


def new_vessel(request):
    if request.method == 'POST' and 'delete' in request.POST:   # 'Delete' on an unsaved vessel = discard
        return redirect('vessel-list')
    form = VesselForm(request.POST or None, initial=None if request.method == 'POST' else NEW_VESSEL)
    if request.method == 'POST' and form.is_valid():
        vessel = form.save()
        messages.success(request, f'Vessel "{vessel.name}" saved.')
        return redirect('edit-vessel', pk=vessel.pk)
    return _edit_page(request, form, None)


def edit_vessel(request, pk):
    vessel = get_object_or_404(Vessel, pk=pk)
    if request.method == 'POST':
        if 'delete' in request.POST:
            vessel.delete()
            messages.success(request, 'Vessel deleted.')
            return redirect('vessel-list')
        form = VesselForm(request.POST, instance=vessel)
        if form.is_valid():
            form.save()
            messages.success(request, 'Vessel saved.')
            return redirect('edit-vessel', pk=vessel.pk)
    else:
        form = VesselForm(instance=vessel)
    return _edit_page(request, form, vessel)


def _png(content):
    response = HttpResponse(content, content_type='image/png')
    response['Cache-Control'] = 'no-store'
    return response


def _posted_vessel(request):
    """(vessel, None): the editor's current (unsaved) values; or (None, the 400 naming the fields that stop it)."""
    data = request.POST.copy()
    if not data.get('name'):
        data['name'] = 'preview'   # a name is only needed to save
    form = VesselForm(data)
    if not form.is_valid():
        fields = {name: {'label': str(form.fields[name].label) if name in form.fields else '', 'errors': list(errors)}
                  for name, errors in form.errors.items()}
        return None, JsonResponse({'error': 'Check the highlighted values.', 'fields': fields}, status=400)
    return form.save(commit=False), None


@require_POST
def vessel_preview(request):
    """The drawing of the editor's current (unsaved) values, or the fields that stop it being drawn."""
    vessel, errors = _posted_vessel(request)
    return errors or _png(render_png(spec_from(vessel)))


def _rounded(value):
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return value


def _scene_json(spec, coverage=()):
    """The drawing as shapes for the browser's interactive SVG (vessel_view.js), with its colours."""
    return JsonResponse({'scene': _rounded(build_scene(spec, coverage).as_dict()),
                         'colours': {name: '#%02x%02x%02x' % rgb for name, rgb in COLOURS.items()}})


@require_POST
def vessel_scene(request):
    """The vessel editor's drawing of its current (unsaved) values."""
    vessel, errors = _posted_vessel(request)
    return errors or _scene_json(spec_from(vessel))


def _coverage(request):
    try:
        return clean_coverage(json.loads(request.GET.get('coverage') or '[]'))
    except ValueError:
        return []


def vessel_coverage_scene(request, pk):
    """A saved vessel's drawing with a report's coverage (?coverage=<JSON marks>), for the report editor."""
    return _scene_json(spec_from(get_object_or_404(Vessel, pk=pk)), _coverage(request))


def vessel_png(request, pk):
    """The saved vessel's drawing; ?coverage=<JSON marks> draws a report's coverage on it (its editor's preview)."""
    return _png(render_png(spec_from(get_object_or_404(Vessel, pk=pk)), _coverage(request)))


def vessel_parts_json(request, pk):
    """What a report's coverage rows can name on the vessel: parts, seams, nozzles, band directions."""
    return JsonResponse(vessel_parts(spec_from(get_object_or_404(Vessel, pk=pk))))
