import csv
import json
import math
import os
from dataclasses import asdict

import numpy as np
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from reports.models import Report

from .models import Indication, OpenedFile
from .paths import PathNotAllowed, allowed_roots, checked_path, in_working_folders, real_path
from .services import browse, detection, geometry, projections, projects, report_export, sizing
from .services.nde_data import (
    RASTER, UNSUPPORTED, Gate, NdeDataError, open_file, read_ascan, read_frame, read_status, usable,
)
from .services.readings import evaluate_gates, gate_letter, omnipc_reading

MAX_FILES = 5000
# Readings the panel shows, when the gates they need exist (OmniPC names)
READINGS = ('A%', 'SA^', 'DA^', 'PA^', 'ViA^', 'B%', 'SB^', 'DB^', 'A/-I/', 'T(B/-A/)')


@ensure_csrf_cookie
def analysis(request):
    """The Analysis page: open an .nde file and look through its data, like OmniPC."""
    return render(request, 'analysis/analysis.html', {'roots': allowed_roots()})


def _error(message, status=400):
    return JsonResponse({'error': message}, status=status)


def files(request):
    """Every .nde file under the working folders: [{path, folder, name, size, modified}], newest first."""
    found = []
    for root in allowed_roots():
        for folder, _, names in os.walk(root):
            for name in names:
                if name.lower().endswith('.nde'):
                    path = os.path.join(folder, name)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    found.append({'path': path, 'folder': os.path.relpath(folder, root), 'root': root, 'name': name,
                                  'size': stat.st_size, 'modified': stat.st_mtime})
                    if len(found) >= MAX_FILES:
                        break
    found.sort(key=lambda f: f['modified'], reverse=True)
    return JsonResponse({'roots': allowed_roots(), 'files': found, 'opened': _opened_files()})


def _opened_files():
    """The files opened from outside the working folders that are still there, newest first."""
    out = []
    for item in OpenedFile.objects.all():
        try:
            stat = os.stat(item.path)
        except OSError:
            continue
        if in_working_folders(item.path):
            continue   # moved under a working folder since: listed there
        out.append({'path': item.path, 'folder': os.path.dirname(item.path), 'root': '', 'name': os.path.basename(item.path),
                    'size': stat.st_size, 'modified': stat.st_mtime, 'opened': True})
    return out


def _open(request):
    """(path, FileInfo) of the request's ?path=, or raises PathNotAllowed / NdeDataError."""
    path = checked_path(request.GET.get('path', ''))
    return path, open_file(path)


def _group(info, request):
    try:
        group = info.group(int(request.GET.get('group', 0)))
    except ValueError:
        raise NdeDataError('Bad group number.')
    if group.layout == UNSUPPORTED:
        raise NdeDataError(group.reason)
    return group


def _int(request, name):
    try:
        return int(request.GET.get(name, ''))
    except ValueError:
        raise NdeDataError(f'Bad {name}.')


def file_info(request):
    """The file's groups (axes, beams, gates), specimen and probe, with each line's ray for the S-scan; SI."""
    try:
        _, info = _open(request)
    except (PathNotAllowed, NdeDataError) as e:
        return _error(str(e))
    data = info.as_dict()
    data['weld_outline'] = geometry.weld_outline(info.weld, info.specimen.get('thickness'), caps=False)
    data['weld_caps'] = geometry.weld_outline(info.weld, info.specimen.get('thickness'), caps='only')
    for group, out in zip(info.groups, data['groups']):
        out['rays'] = [asdict(r) for r in geometry.frame_rays(group)] if group.layout != UNSUPPORTED else []
        out['synced_to_interface'] = group.synced_to_interface
    return JsonResponse(data)


def frame(request):
    """
    The raw samples at one scan position: little-endian int16 [lateral x samples], then (when the
    file has them) the A-scan status bytes [lateral]. Shape in X-Lateral / X-Samples / X-Status.
    """
    try:
        path, info = _open(request)
        group = _group(info, request)
        amplitudes, status = read_frame(path, group, _int(request, 'scan'))
    except (PathNotAllowed, NdeDataError) as e:
        return _error(str(e))
    body = amplitudes.astype('<i2', copy=False).tobytes()
    if status is not None:
        body += status.astype(np.uint8, copy=False).tobytes()
    response = HttpResponse(body, content_type='application/octet-stream')
    response['X-Lateral'], response['X-Samples'] = amplitudes.shape
    response['X-Status'] = '1' if status is not None else '0'
    response['Cache-Control'] = 'private, max-age=600'
    return response


def _gates(request, group):
    """The file's gates, or the editor's own (?gates= JSON list, SI: start / length in s from the
    pulse or from the sync gate's crossing, threshold in %; a TrueDepth gate's depth_start / depth_end
    and a Box gate's index_start / index_end in m - those two are always from the pulse; a floating
    gate's float_db, float_ref and float_floor - see readings.gate_level)."""
    text = request.GET.get('gates')
    if not text:
        return group.gates
    try:
        items = json.loads(text)
        gates = []
        for item in items:
            geometry = item.get('geometry') if item.get('geometry') in ('TrueDepth', 'Box') else 'SoundPath'
            sync = item.get('sync_gate') if geometry == 'SoundPath' else None
            extra = {}
            if geometry != 'SoundPath':
                names = ('depth_start', 'depth_end') + (('index_start', 'index_end') if geometry == 'Box' else ())
                extra = {name: float(item[name]) for name in names}
                if not all(math.isfinite(v) for v in extra.values()):
                    raise ValueError
                if geometry == 'Box':
                    extra['outside'] = 'zero' if item.get('outside') == 'zero' else 'none'
            if item.get('float_db') is not None:   # a floating gate
                extra.update(float_db=float(item['float_db']), float_ref=float(item.get('float_ref') or 80.0),
                             float_floor=float(item.get('float_floor') or 0.0))
                if not (0 <= extra['float_db'] <= 40 and 1 <= extra['float_ref'] <= 1000 and 0 <= extra['float_floor'] <= 1000):
                    raise ValueError
            gate = Gate(
                id=int(item['id']), name=str(item.get('name') or '')[:20], start=float(item['start']),
                length=float(item['length']), threshold=float(item['threshold']),
                sync_mode='GateRelative' if sync is not None else 'Pulse',
                sync_gate=int(sync) if sync is not None else None,
                trigger='MaxPeak' if item.get('trigger') == 'MaxPeak' else 'Crossing',
                geometry=geometry, **extra,
            )
            if gate.length <= 0 or not 0 <= gate.threshold <= 1000:
                raise ValueError
            gates.append(gate)
    except (ValueError, TypeError, KeyError):
        raise NdeDataError("The gates couldn't be read.")
    return gates


def readings(request):
    """
    Gates and OmniPC readings on one A-scan (services/readings.py, checked against OmniPC), with soft
    gain ?gain= dB applied first. Lengths in m, times in s, amplitudes in the file's unit (%).
    """
    try:
        path, info = _open(request)
        group = _group(info, request)
        lateral = _int(request, 'lateral')
        scan = _int(request, 'scan')
        raw = read_ascan(path, group, scan, lateral)
        status = read_status(path, group, scan, lateral)
        gain = float(request.GET.get('gain') or 0)
        gates = _gates(request, group)
    except (PathNotAllowed, NdeDataError, ValueError) as e:
        return _error(str(e))
    if gain:
        raw = np.clip(np.round(raw.astype(np.float64) * 10 ** (gain / 20)), -32768, 32767).astype(np.int16)
    if not usable(group, status):
        note = 'No interface sync (gate I) on this A-scan.' if status & 1 else 'No data on this A-scan.'
        return JsonResponse({'gates': {}, 'readings': {}, 'note': note})
    beam = group.beams[lateral]
    results = evaluate_gates(group, beam, raw, gates)
    values = {}
    # On a 0 deg raster the peak's index position is just the line's: OmniPC doesn't list PA^ / ViA^
    skipped = ('PA^', 'ViA^', 'PB^', 'ViB^') if group.layout == RASTER else ()
    for name in READINGS:
        if name in skipped:
            continue
        try:
            value = omnipc_reading(name, results, beam, info)
        except KeyError:
            continue
        if value is not None:
            values[name] = value
    return JsonResponse({'gates': {k: asdict(v) for k, v in results.items()}, 'readings': values})


# ── Whole-file views: C-scan and B-scan (services/projections.py) ───────

def _whole_file(request):
    """(path, info, group, gates, gain) for a projections request."""
    path, info = _open(request)
    group = _group(info, request)
    try:
        gain = float(request.GET.get('gain') or 0)
    except ValueError:
        raise NdeDataError('Bad gain.')
    return path, info, group, _gates(request, group), gain


def projections_status(request):
    """Starts building the file's C-scan / B-scan data if needed: {'state', 'progress', 'error'}."""
    try:
        path, _, group, gates, gain = _whole_file(request)
    except (PathNotAllowed, NdeDataError) as e:
        return _error(str(e))
    return JsonResponse(projections.ensure(path, group, gates, gain))


def _binary(array, **headers):
    response = HttpResponse(np.ascontiguousarray(array).tobytes(), content_type='application/octet-stream')
    for name, value in headers.items():
        response[f"X-{name.replace('_', '-').title()}"] = str(value)
    response['Cache-Control'] = 'private, max-age=600'
    return response


def cscan(request):
    """
    A C-scan as little-endian float32 [scans x lines] (NaN = nothing), for ?gate= and ?kind=:
    amplitude (%), depth (true depth of the gate's peak, folded at the back wall, m), or thickness
    (?gate=B&from=A: depth between the two gates' crossings, m).
    """
    try:
        path, info, group, gates, gain = _whole_file(request)
    except (PathNotAllowed, NdeDataError) as e:
        return _error(str(e))
    data = projections.read_cscan(path, group, gates, gain)
    if data is None:
        return JsonResponse({'error': 'Not built yet.', **projections.ensure(path, group, gates, gain)}, status=409)
    letter, kind = request.GET.get('gate', 'A').upper(), request.GET.get('kind', 'amplitude')
    if f'{letter}_amplitude' not in data:
        return _error(f'There is no gate {letter}.')
    velocity = np.array([b.velocity for b in group.beams], dtype=np.float64)
    cos = np.cos(np.radians([b.refracted_angle for b in group.beams]))
    if kind == 'amplitude':
        values = data[f'{letter}_amplitude']
    elif kind == 'depth':
        # The peak only counts where the signal broke the gate (like SA^ / DA^)
        peak = np.where(np.isnan(data[f'{letter}_crossing_time']), np.nan, data[f'{letter}_peak_time'])
        depth = velocity * peak / 2 * cos
        thickness = info.specimen.get('thickness')
        if thickness:
            leg = np.floor(depth / thickness)
            within = depth - leg * thickness
            depth = np.where(leg % 2 == 0, within, thickness - within)
        values = depth
    elif kind == 'thickness':
        other = request.GET.get('from', 'A').upper()
        if f'{other}_crossing_time' not in data:
            return _error(f'There is no gate {other}.')
        values = velocity * (data[f'{letter}_crossing_time'] - data[f'{other}_crossing_time']) / 2 * cos
    else:
        return _error('Unknown C-scan kind.')
    values = np.asarray(values, dtype='<f4')
    finite = values[np.isfinite(values)]
    return _binary(values, scans=values.shape[0], lines=values.shape[1],
                   min=float(finite.min()) if finite.size else 0, max=float(finite.max()) if finite.size else 0)


def bscan(request):
    """One line's B-scan from the cached volume: uint8 [scans x bins] (255 = X-Full %)."""
    try:
        path, _, group, gates, gain = _whole_file(request)
        line = _int(request, 'line')
    except (PathNotAllowed, NdeDataError) as e:
        return _error(str(e))
    if not 0 <= line < group.shape[1]:
        return _error('That line is outside the data.')
    values, meta = projections.read_volume_line(path, group, line)
    if values is None:
        return JsonResponse({'error': 'Not built yet.', **projections.ensure(path, group, gates, gain)}, status=409)
    return _binary(values, scans=meta['scans'], bins=meta['bins'], factor=meta['factor'], full=meta['full'])


def size_indication(request):
    """
    Length (along the scan) or width (along a raster's index axis) of the indication at the cursor,
    by an amplitude drop (?method=6 / 12 / 20 dB) or down to the gate threshold (?method=threshold),
    on the cached gate map; ?lines=all sizes the most of every line at each scan position.
    """
    try:
        path, info, group, gates, gain = _whole_file(request)
        scan, line = _int(request, 'scan'), _int(request, 'lateral')
    except (PathNotAllowed, NdeDataError) as e:
        return _error(str(e))
    data = projections.read_cscan(path, group, gates, gain)
    if data is None:
        return JsonResponse({'error': 'Not built yet.', **projections.ensure(path, group, gates, gain)}, status=409)
    letter = request.GET.get('gate', 'A').upper()
    gate = next((g for g in gates if gate_letter(g.name) == letter), None)
    try:
        result = sizing.size_length(
            data, group, letter, scan, line, axis=request.GET.get('axis', 'scan'),
            lines=request.GET.get('lines', 'current'), method=request.GET.get('method', '6'),
            threshold=gate.threshold if gate else None)
    except sizing.SizingError as e:
        return _error(str(e))
    return JsonResponse(result)


# ── Find indications: every signal in a gate over its threshold, sized ──

def _settings(data):
    """Find-indications settings from the JSON body, checked: gate, threshold, method, merge gap, minimums."""
    def number(name, default, lo, hi):
        value = data.get(name, default)
        if value in (None, ''):
            return default
        value = float(value)
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(name)
        return value

    method = str(data.get('method') or '6')
    if method not in sizing.METHODS:
        raise ValueError('method')
    return {
        'letter': str(data.get('gate') or 'A').upper()[:1],
        'threshold': number('threshold', None, 0, 1000),
        'method': method,
        'merge_gap': int(number('merge_gap', 2, 0, 1000)),
        'min_length': number('min_length', 0.0, 0, 10),
        'min_lines': int(number('min_lines', 1, 1, 10000)),
    }


def _auto_indication(path, info, group, sized, number):
    # Index as on a hand-added one: the index line on a raster, else the probe's index position (the axial
    # position, PA^, is in the sizing)
    index = sized.get('axial') if group.layout == RASTER else info.probe.get('v_offset')
    return Indication(
        file_path=path, file_name=os.path.basename(path), group=group.id, number=number,
        scan=sized['peak_scan'], lateral=sized['peak_line'], scan_position=sized['scan_position'],
        index_position=index, angle=sized.get('angle'), gain=sized['gain_db'],
        readings=detection.readings_of(sized), sizing=sized,
        status=Indication.UNREVIEWED, source=Indication.AUTO)


@require_http_methods(['POST'])
def detect_indications(request):
    """
    Finds and sizes every indication in a gate (query: path, group, gates, gain as for the C-scan; JSON
    body: gate, threshold, method 6 / 12 / 20, merge_gap in scan positions, min_length in m, min_lines).
    The file's unreviewed found indications on this group are replaced; reviewed and hand-added ones
    are kept, and a find on top of one of them is left out. 409 while the C-scan is being built.
    """
    try:
        path, info, group, gates, gain = _whole_file(request)
        options = _settings(json.loads(request.body or b'{}'))
    except (PathNotAllowed, NdeDataError) as e:
        return _error(str(e))
    except (ValueError, TypeError) as e:
        return _error(f"The settings couldn't be read ({e}).")
    data = projections.read_cscan(path, group, gates, gain)
    if data is None:
        return JsonResponse({'error': 'Not built yet.', **projections.ensure(path, group, gates, gain)}, status=409)
    letter = options.pop('letter')
    try:
        found, skipped = detection.detect(path, info, group, gates, data, letter, gain=gain, **options)
    except (ValueError, NdeDataError) as e:
        return _error(str(e))
    on_group = Indication.objects.filter(file_path=path, group=group.id)
    with transaction.atomic():
        on_group.filter(source=Indication.AUTO, status=Indication.UNREVIEWED).delete()
        kept = list(on_group)
        last = Indication.objects.filter(file_path=path).aggregate(m=Max('number'))['m'] or 0
        added, overlapping = [], 0
        for sized in found:
            if any(detection.overlaps(sized, item) for item in kept):
                overlapping += 1
                continue
            last += 1
            added.append(_auto_indication(path, info, group, sized, last))
        Indication.objects.bulk_create(added)
    return JsonResponse({
        'found': len(added), 'kept': len(kept), 'overlapping': overlapping,
        'skipped': [s['error'] for s in skipped],
        'indications': [i.as_dict() for i in Indication.objects.filter(file_path=path)],
    })


MANUAL_SIZING = ('scan_start', 'scan_end', 'view_top', 'view_bottom', 'top', 'bottom', 'axial_start', 'axial_end')


@require_http_methods(['POST'])
def resize_indication(request, pk):
    """
    Sizes a found indication again (query: path, group, gates, gain; JSON body {method}: 6 / 12 / 20 dB),
    or takes the user's own ends ({manual: {scan_start, scan_end, view_top, view_bottom, axial_start,
    axial_end}}, m; view_top / view_bottom as the S-scan draws depth, unfolded - or top / bottom, true
    depths): the length, height and axial extent follow, it's marked edited, and the sizing it had
    first is kept as 'original'.
    """
    item = get_object_or_404(Indication, pk=pk)
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        return _error("The change couldn't be read.")
    old = dict(item.sizing or {})
    original = old.pop('original', None) or {k: v for k, v in old.items()}
    manual = body.get('manual')
    if isinstance(manual, dict):
        new = dict(old)
        try:
            for name in MANUAL_SIZING:
                if manual.get(name) is not None:
                    value = float(manual[name])
                    if not math.isfinite(value):
                        raise ValueError(name)
                    new[name] = value
        except (TypeError, ValueError):
            return _error("The sizing couldn't be read.")
        for lo, hi in (('scan_start', 'scan_end'), ('view_top', 'view_bottom'), ('top', 'bottom'), ('axial_start', 'axial_end')):
            if new.get(lo) is not None and new.get(hi) is not None and new[lo] > new[hi]:
                new[lo], new[hi] = new[hi], new[lo]
        if 'view_top' in manual and new.get('view_top') is not None and new.get('view_bottom') is not None:
            new['top'], new['bottom'] = sizing.folded_span(new['view_top'], new['view_bottom'], new.get('thickness'))
        if new.get('scan_start') is not None and new.get('scan_end') is not None:
            new['length'] = new['scan_end'] - new['scan_start']
        if new.get('top') is not None and new.get('bottom') is not None:
            new['height'] = new['bottom'] - new['top']
            new['depth'] = new['top']
        new['edited'] = True
    else:
        try:
            path, info, group, gates, gain = _whole_file(request)
        except (PathNotAllowed, NdeDataError) as e:
            return _error(str(e))
        if path != item.file_path or group.id != item.group:
            return _error('That indication is in another file or group.')
        method = str(body.get('method') or old.get('method') or '6')
        letter = old.get('gate') or 'A'
        data = projections.read_cscan(path, group, gates, gain)
        if data is None:
            return JsonResponse({'error': 'Not built yet.', **projections.ensure(path, group, gates, gain)}, status=409)
        region = {'peak_scan': old.get('peak_scan', item.scan), 'peak_line': old.get('peak_line', item.lateral),
                  'line_lo': old.get('line_lo', item.lateral), 'line_hi': old.get('line_hi', item.lateral)}
        try:
            new = sizing.size_indication(path, info, group, gates, data, letter, region, method, gain)
        except sizing.SizingError as e:
            return _error(str(e))
        new.update({k: old[k] for k in ('scan_lo', 'scan_hi', 'detect_threshold') if k in old})
        item.scan, item.lateral = new['peak_scan'], new['peak_line']
        item.scan_position = new['scan_position']
        if group.layout == RASTER:
            item.index_position = new.get('axial')
        item.gain = new['gain_db']
    if old.get('auto') or old.get('edited'):
        new['original'] = original
    item.sizing = new
    item.readings = {**(item.readings or {}), **detection.readings_of(new)}
    item.save()
    return JsonResponse(item.as_dict())


# ── Indications (like OmniPC's indication table) ─────────────────────────

def _float_or_none(value):
    try:
        return None if value in (None, '') else float(value)
    except (TypeError, ValueError):
        return None


@require_http_methods(['GET', 'POST'])
def indications(request):
    """
    GET ?path=: the file's indications. POST (JSON: path, group, scan, lateral, positions, readings,
    cursors, sizing, gain, comment): saves one, numbered after the file's last.
    """
    if request.method == 'GET':
        try:
            path = checked_path(request.GET.get('path', ''))
        except PathNotAllowed as e:
            return _error(str(e))
        return JsonResponse({'indications': [i.as_dict() for i in Indication.objects.filter(file_path=path)]})
    try:
        data = json.loads(request.body or b'{}')
        path = checked_path(data.get('path', ''))
        scan, lateral = int(data['scan']), int(data['lateral'])
    except (ValueError, KeyError, TypeError, PathNotAllowed) as e:
        return _error(str(e) or "The indication couldn't be read.")
    last = Indication.objects.filter(file_path=path).aggregate(m=Max('number'))['m'] or 0
    dicts = {name: data.get(name) if isinstance(data.get(name), dict) else {} for name in ('readings', 'cursors', 'sizing')}
    item = Indication.objects.create(
        file_path=path, file_name=os.path.basename(path), group=int(data.get('group') or 0), number=last + 1,
        scan=scan, lateral=lateral, scan_position=_float_or_none(data.get('scan_position')),
        index_position=_float_or_none(data.get('index_position')), angle=_float_or_none(data.get('angle')),
        gain=_float_or_none(data.get('gain')) or 0, comment=str(data.get('comment') or '')[:2000], **dicts)
    return JsonResponse(item.as_dict(), status=201)


# What "Clear" in the Find box removes from a group: the filters on its indications
CLEAR_WHICH = {
    'unreviewed': {'source': Indication.AUTO, 'status': Indication.UNREVIEWED},   # found, not reviewed yet
    'rejected': {'status': Indication.REJECTED},                                  # rejected, found or added
    'found': {'source': Indication.AUTO},                                         # everything found
    'all': {},                                                                    # everything, added ones too
}


@require_http_methods(['POST'])
def clear_indications(request):
    """POST (JSON path, group, which: unreviewed / rejected / found / all): deletes those indications of
    the file's group; returns how many and the file's indications left."""
    try:
        data = _json_body(request)
        path = checked_path(data.get('path', ''))
        group = int(data.get('group') or 0)
        which = CLEAR_WHICH[data.get('which')]
    except (ValueError, TypeError, PathNotAllowed) as e:
        return _error(str(e) or "The request couldn't be read.")
    except KeyError:
        return _error('Clear which indications?')
    deleted, _ = Indication.objects.filter(file_path=path, group=group, **which).delete()
    return JsonResponse({'deleted': deleted,
                         'indications': [i.as_dict() for i in Indication.objects.filter(file_path=path)]})


@require_http_methods(['POST', 'DELETE'])
def indication(request, pk):
    """POST (JSON {comment} and / or {status}: unreviewed / accepted / rejected): edits an indication; DELETE removes it."""
    item = get_object_or_404(Indication, pk=pk)
    if request.method == 'DELETE':
        item.delete()
        return JsonResponse({'deleted': pk})
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return _error("The change couldn't be read.")
    fields = ['updated_at']
    if 'comment' in data:
        item.comment = str(data['comment'] or '')[:2000]
        fields.append('comment')
    if 'status' in data:
        if data['status'] not in dict(Indication.STATUS_CHOICES):
            return _error('Unknown status.')
        item.status = data['status']
        fields.append('status')
    item.save(update_fields=fields)
    return JsonResponse(item.as_dict())


# OmniPC's indication table columns, then any other readings the indications carry
CSV_READINGS = ('A%', 'DA^', 'PA^', 'SA^', 'ViA^', 'B%', 'A/-I/', 'T(B/-A/)', 'U(m-r)', 'I(m-r)', 'S(m-r)',
                'Length', 'TminZ')


def indications_csv(request):
    """The file's indications as a CSV like OmniPC's indications.csv (?units=in or mm)."""
    try:
        path = checked_path(request.GET.get('path', ''))
    except PathNotAllowed as e:
        return _error(str(e))
    unit, scale = ('mm', 1000.0) if request.GET.get('units') == 'mm' else ('in', 1 / 0.0254)
    items = list(Indication.objects.filter(file_path=path))
    extra = sorted({name for i in items for name in i.readings} - set(CSV_READINGS))
    columns = list(CSV_READINGS) + extra

    def length(v):
        return '' if v is None else f'{v * scale:.3f} {unit}'

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    stem = os.path.splitext(os.path.basename(path))[0]
    response['Content-Disposition'] = f'attachment; filename="{stem} indications.csv"'
    response.write('﻿')
    writer = csv.writer(response)
    writer.writerow(['#', 'Group', 'Scan', 'Index', 'Angle', *columns, 'Comment'])
    for i in items:
        row = [i.number, f'GR-{i.group + 1}', length(i.scan_position), length(i.index_position),
               '' if i.angle is None else f'{i.angle:.3f}']
        for name in columns:
            value = i.readings.get(name)
            if value is None:
                row.append('')
            elif '%' in name:
                row.append(f'{value:.3f} %')
            elif 'dB' in name:
                row.append(f'{value:.1f} dB')
            else:
                row.append(length(value))
        row.append(i.comment)
        writer.writerow(row)
    return response


# ── Send indications to a report ──

def report_targets(request):
    """GET ?path=: draft reports to send indications to (those made from this file's job folder first)."""
    return JsonResponse({'reports': report_export.draft_reports(request.GET.get('path', ''))})


def _send_request(request):
    """(data, report, indications) of a send / preview request, or raises ValueError with the message."""
    try:
        data = json.loads(request.body or b'{}')
        report = Report.objects.filter(pk=int(data.get('report'))).first()
        ids = [int(i) for i in data.get('indications') or []]
    except (ValueError, TypeError):
        raise ValueError("The request couldn't be read.")
    if report is None:
        raise ValueError("That report doesn't exist any more.")
    by_id = {i.pk: i for i in Indication.objects.filter(pk__in=ids)}
    indications = [by_id[i] for i in ids if i in by_id]
    if not indications:
        raise ValueError('Pick the indications to send.')
    return data, report, indications


@require_http_methods(['POST'])
def report_preview(request):
    """POST (JSON report, indications [ids], units): the rows they'd make, in the report's columns."""
    try:
        data, report, indications = _send_request(request)
    except ValueError as e:
        return _error(str(e))
    units = 'mm' if data.get('units') == 'mm' else 'in'
    out = report_export.preview(report, indications, units)
    out['report'] = {'id': report.pk, 'name': report.document_filename or f'Report {report.pk}',
                     'type': report.report_type, 'issued': report.is_issued,
                     'has_rows': bool(getattr(report, 'results_table', None) and report.results_table.rows.exists())}
    out['field_names'] = report_export.FIELDS
    return JsonResponse(out)


@require_http_methods(['POST'])
def report_send(request):
    """
    POST (JSON report, indications [ids], columns, rows [[cells]], pictures [data URL | null]):
    adds the rows (as previewed, maybe edited) and pictures to the report's results.
    """
    try:
        data, report, indications = _send_request(request)
    except ValueError as e:
        return _error(str(e))
    rows = data.get('rows')
    if not isinstance(rows, list) or len(rows) != len(indications) or not all(isinstance(r, list) for r in rows):
        return _error('Each indication needs its row.')
    captions = [f'{i.file_name} - indication {i.number}' for i in indications]
    try:
        added = report_export.append(report, data.get('columns') or [], rows, data.get('pictures'), captions)
    except report_export.ExportError as e:
        return _error(str(e), status=409)
    return JsonResponse({'added': added, 'edit_url': reverse('edit-report', args=[report.pk])})


@require_http_methods(['POST'])
def weld_outline(request):
    """POST (JSON weld, thickness): the outline of a weld as edited on the page (the same drawing as the file's)."""
    try:
        data = json.loads(request.body or b'{}')
        thickness = float(data.get('thickness'))
    except (ValueError, TypeError):
        return _error("The weld couldn't be read.")
    if not (0 < thickness < 1):
        return _error('The part thickness is needed to draw the weld.')
    weld = geometry.clean_weld(data.get('weld'))
    return JsonResponse({'weld': weld, 'lines': geometry.weld_outline(weld, thickness, caps=False),
                         'caps': geometry.weld_outline(weld, thickness, caps='only')})


# ── Files from anywhere on this PC, and new projects from them ──

def browse_pc(request):
    """GET ?path=: a folder's sub-folders and .nde files; no path: the drives and usual places."""
    path = request.GET.get('path', '')
    if not path:
        return JsonResponse({'path': '', 'parent': '', 'places': browse.places(), 'folders': [], 'files': []})
    try:
        return JsonResponse(browse.listing(path))
    except ValueError as e:
        return _error(str(e))


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        raise ValueError("The request couldn't be read.")
    return data if isinstance(data, dict) else {}


@require_http_methods(['POST'])
def open_external(request):
    """POST (JSON path): opens a .nde file from anywhere on this PC - checked, then recorded so the page may read it."""
    try:
        data = _json_body(request)
        path = str(data.get('path') or '')
        real = real_path(path)
        if not real.endswith('.nde') or not os.path.isfile(real):
            raise ValueError('Pick a .nde file.')
        open_file(real)   # a readable .nde (raises NdeDataError otherwise)
    except (ValueError, NdeDataError) as e:
        return _error(str(e))
    item, _ = OpenedFile.objects.update_or_create(path=real, defaults={'name': os.path.basename(real)})
    return JsonResponse({'path': real, 'name': item.name, 'in_working_folders': in_working_folders(real)})


@require_http_methods(['POST'])
def forget_external(request):
    """POST (JSON path): takes a file off the opened list (it can't be read again until reopened)."""
    try:
        data = _json_body(request)
    except ValueError as e:
        return _error(str(e))
    deleted, _ = OpenedFile.objects.filter(path=real_path(str(data.get('path') or 'x'))).delete()
    return JsonResponse({'forgotten': bool(deleted)})


def _project_paths(data):
    paths = data.get('paths') or []
    if not isinstance(paths, list):
        raise ValueError('Pick the .nde files for the project.')
    try:
        checked = [checked_path(str(p)) for p in paths]
    except PathNotAllowed as e:
        raise ValueError(str(e))
    return list(dict.fromkeys(checked))


@require_http_methods(['POST'])
def project_options(request):
    """POST (JSON paths): the report types and working folders a new project can go in, and a name for it."""
    try:
        paths = _project_paths(_json_body(request))
    except ValueError as e:
        return _error(str(e))
    out = projects.options(paths)
    out['files'] = [{'path': p, 'name': os.path.basename(p), 'size': os.path.getsize(p)} for p in paths]
    return JsonResponse(out)


@require_http_methods(['POST'])
def project_start(request):
    """POST (JSON paths, type, name): makes the job folder and starts copying the files into it."""
    try:
        data = _json_body(request)
        paths = _project_paths(data)
        job = projects.start(paths, str(data.get('type') or ''), str(data.get('name') or ''))
    except (ValueError, projects.ProjectError) as e:
        return _error(str(e))
    return JsonResponse({'job': job, **projects.status(job)})


def project_status(request):
    """GET ?job=: how the copying is going; when done, where Guided Creation picks up."""
    job = projects.status(request.GET.get('job', ''))
    if job is None:
        return _error('That project job is unknown (was the server restarted?).', status=404)
    return JsonResponse(job)


def frame_gates(request):
    """
    Every beam's gate windows at one scan line, for drawing the gates on the S-scan:
    {letters, windows: {letter: [[start, end] s | null per beam]}, paths: the same as sound paths (m),
    crossings: {letter: [s | null]}}.
    Same rules as the readings (synced gates follow each beam's own sync crossing).
    """
    try:
        path, info = _open(request)
        group = _group(info, request)
        scan = _int(request, 'scan')
        raw, status = read_frame(path, group, scan)
        gain = float(request.GET.get('gain') or 0)
        gates = _gates(request, group)
    except (PathNotAllowed, NdeDataError, ValueError) as e:
        return _error(str(e))
    if gain:
        raw = np.clip(np.round(raw.astype(np.float64) * 10 ** (gain / 20)), -32768, 32767).astype(np.int16)
    letters = [gate_letter(g.name) for g in gates]
    windows = {letter: [] for letter in letters}
    paths = {letter: [] for letter in letters}
    crossings = {letter: [] for letter in letters}
    for line, beam in enumerate(group.beams):
        results = {}
        if status is None or usable(group, int(status[line])):
            results = evaluate_gates(group, beam, raw[line], gates)
        for letter in letters:
            r = results.get(letter)
            ok = r is not None and r.found and r.start is not None
            windows[letter].append([r.start, r.end] if ok else None)
            paths[letter].append([beam.velocity * r.start / 2, beam.velocity * r.end / 2] if ok else None)
            crossings[letter].append(r.crossing_time if ok else None)
    return JsonResponse({'letters': letters, 'windows': windows, 'paths': paths, 'crossings': crossings})
