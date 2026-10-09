"""
The inventory as the report editor's serial number pickers offer it (reports/js/inventory_pick.js):
each serial number field (a setup's scope, probe and cal block; the weld form's instrument, probe
columns and additional blocks) lists the inventory's serials, and picking one fills the fields
beside it with what the inventory knows.
"""
from reports.weld_columns import columns_from_setup

from .inventory import with_library_scope
from .models import CalibrationBlock, Probe, Scope


def _clean(values):
    return {k: v for k, v in values.items() if v not in (None, '')}


def _key(serial):
    return serial.strip().upper()


def inventory_picks():
    """
    {'scopes' | 'probes' | 'blocks': {SERIAL: {'serial', 'label', <part>: {field: value}}}}, where a part
    is the fields a pick fills: 'setup' (a setup block's fields), 'weld' (the weld form's instrument
    card or additional block, without its add<N>_ prefix) or 'column' (a weld probe column).
    """
    scopes, probes, blocks = {}, {}, {}
    for scope in Scope.objects.exclude(serial_number=''):
        setup, _ = with_library_scope({'scope_serial': scope.serial_number})
        scopes.setdefault(_key(scope.serial_number), {
            'serial': scope.serial_number,
            'label': ' · '.join(filter(None, [scope.name or scope.model, scope.manufacturer])),
            'setup': _clean(setup),
            'weld': _clean(columns_from_setup(setup)['instrument']),
        })
    for probe in Probe.objects.exclude(serial_number=''):
        probes.setdefault(_key(probe.serial_number), {
            'serial': probe.serial_number,
            'label': ' · '.join(filter(None, [probe.model, probe.frequency, probe.manufacturer])),
            'setup': _clean({'transducer_model': probe.model, 'transducer_serial': probe.serial_number,
                             'freq': probe.frequency, 'elements': probe.elements, 'probe_diameter': probe.diameter}),
            'column': _clean({'model': probe.model, 'make': probe.manufacturer, 'frequency': probe.frequency,
                              'serial': probe.serial_number}),
        })
    for block in CalibrationBlock.objects.exclude(serial_number=''):
        blocks.setdefault(_key(block.serial_number), {
            'serial': block.serial_number,
            'label': ' · '.join(filter(None, [block.block_type, block.material])),
            'setup': _clean({'cal_block_type': block.block_type, 'cal_block_serial': block.serial_number,
                             'cal_material': block.material}),
            'weld': _clean({'block_type': block.block_type, 'serial': block.serial_number, 'material': block.material}),
        })
    return {'scopes': scopes, 'probes': probes, 'blocks': blocks}
