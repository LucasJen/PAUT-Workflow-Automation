import csv
import json
import os
from dataclasses import asdict

import numpy as np
from django.http import HttpResponse, JsonResponse
from django.db.models import Max
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import Indication
from .paths import PathNotAllowed, allowed_roots, checked_path
from .services import geometry, projections, sizing
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
    return JsonResponse({'roots': allowed_roots(), 'files': found})


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
    pulse or from the sync gate's crossing, threshold in %)."""
    text = request.GET.get('gates')
    if not text:
        return group.gates
    try:
        items = json.loads(text)
        gates = []
        for item in items:
            sync = item.get('sync_gate')
            gate = Gate(
                id=int(item['id']), name=str(item.get('name') or '')[:20], start=float(item['start']),
                length=float(item['length']), threshold=float(item['threshold']),
                sync_mode='GateRelative' if sync is not None else 'Pulse',
                sync_gate=int(sync) if sync is not None else None,
                trigger='MaxPeak' if item.get('trigger') == 'MaxPeak' else 'Crossing',
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


@require_http_methods(['POST', 'DELETE'])
def indication(request, pk):
    """POST (JSON {comment}): edits an indication's comment; DELETE removes it."""
    item = get_object_or_404(Indication, pk=pk)
    if request.method == 'DELETE':
        item.delete()
        return JsonResponse({'deleted': pk})
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return _error("The change couldn't be read.")
    if 'comment' in data:
        item.comment = str(data['comment'] or '')[:2000]
        item.save(update_fields=['comment', 'updated_at'])
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
