"""The weld report's Sensitivity block & test material card: Auto-detect from the scanned part."""
import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from ..materials import block_encoder, block_values, detect_block, part_values


@require_POST
def detect_sensitivity_block(request):
    """
    POST scan_part (the JSON the .nde imports recorded) -> {ok, message, values, encoder}: the
    library block for that part's diameter and wall, with the item inspected as scanned.
    """
    try:
        part = json.loads(request.POST.get('scan_part') or '{}') or {}
    except ValueError:
        part = {}
    if not isinstance(part, dict):
        part = {}
    block, why = detect_block(part)
    if block is None:
        return JsonResponse({'ok': False, 'message': why, 'values': part_values(part)})
    message = why or f'Sensitivity block {block} ({block.serial_number}) for the scanned part.'
    if part.get('source'):
        message += f' Part from {part["source"]}.'
    return JsonResponse({'ok': True, 'message': message, 'encoder': block_encoder(block),
                         'values': {**block_values(block), **part_values(part, block)}})
