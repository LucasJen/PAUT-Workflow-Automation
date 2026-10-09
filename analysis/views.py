import os
from dataclasses import asdict

import numpy as np
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from .paths import PathNotAllowed, allowed_roots, checked_path
from .services import geometry
from .services.nde_data import RASTER, UNSUPPORTED, NdeDataError, open_file, read_ascan, read_frame
from .services.readings import evaluate_gates, omnipc_reading

MAX_FILES = 5000
# Readings the panel shows, when the gates they need exist (OmniPC names)
READINGS = ('A%', 'SA^', 'DA^', 'PA^', 'ViA^', 'B%', 'SB^', 'DB^', 'A/-I/', 'T(B/-A/)')


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


def readings(request):
    """
    Gates and OmniPC readings on one A-scan (services/readings.py, checked against OmniPC), with soft
    gain ?gain= dB applied first. Lengths in m, times in s, amplitudes in the file's unit (%).
    """
    try:
        path, info = _open(request)
        group = _group(info, request)
        lateral = _int(request, 'lateral')
        raw = read_ascan(path, group, _int(request, 'scan'), lateral)
        gain = float(request.GET.get('gain') or 0)
    except (PathNotAllowed, NdeDataError, ValueError) as e:
        return _error(str(e))
    if gain:
        raw = np.clip(np.round(raw.astype(np.float64) * 10 ** (gain / 20)), -32768, 32767).astype(np.int16)
    beam = group.beams[lateral]
    results = evaluate_gates(group, beam, raw)
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
