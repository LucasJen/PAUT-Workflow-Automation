"""
Setup values -> the weld form grid's columns: the testing instrument, a probe column and a group
column, written as the weld form shows them (units added). Used by "Import .nde" (one group per
inspection group in the file) and "Load saved setup" in the editor's grid. Migration 0037
converted existing weld reports by the same rules.
"""
import re

from .weld_form import CONV_LONG, CONV_SHEAR, PAUT

NUMBER = re.compile(r'^-?\d+(\.\d+)?$')


def _s(value):
    return '' if value is None else str(value).strip()


def with_unit(value, unit):
    value = _s(value)
    return f'{value}{unit}' if NUMBER.match(value) else value


def kind(values):
    """PAUT unless the setup is conventional: then 0° L-wave or SW by its wave mode."""
    if _s(values.get('beam_formation')).lower() != 'conventional':
        return PAUT
    return CONV_LONG if _s(values.get('wave_propagation')) == 'Longitudinal' else CONV_SHEAR


def _vpa(values):
    aperture, step = _s(values.get('element_aperture')), _s(values.get('element_step'))
    if 'sector' in _s(values.get('beam_formation')).lower() or not (aperture and step):
        return 'N/A'
    return f'{aperture} ele / {step} ele'


def scan_encoder(resolution):
    """
    The weld form's Encoder Cal.: the scan axis' steps only, as the form writes them:
    'Scan 480.58 steps/in; Index 100 steps/in' -> '480.58 steps/in'. Text without a step count is
    kept as it is.
    """
    match = re.search(r'(-?\d+(?:\.\d+)?)\s*steps?\s*/\s*(in|mm)', _s(resolution))
    return f'{match.group(1)} steps/{match.group(2)}' if match else _s(resolution)


def probe_key(probe):
    """Model and S/N: the same probe in two groups (or already a column) shares one column."""
    model, serial = _s(probe.get('model')).lower(), _s(probe.get('serial')).lower()
    return f'{model}|{serial}' if model else ''


def columns_from_setup(values):
    """
    {setup field: value} (a saved setup's fields, or one group of an .nde file) ->
    {'instrument': {...}, 'probe': {...}, 'group': {...}, 'probe_key': ...}, leaving out empty values.
    """
    length = ' mm' if values.get('units') == 'metric' else '"'
    instrument = {
        'inst_name': _s(values.get('scope_platform')) or _s(values.get('scope_model')),
        'inst_manufacturer': values.get('scope_manufacturer') or values.get('manufacturer'),
        'inst_model': values.get('scope_model'),
        'inst_serial': values.get('scope_serial'),
        'inst_cal_due': values.get('scope_cal_due'),
        'inst_module_model': values.get('module_model'),
        'inst_module_serial': values.get('module_serial'),
        'inst_module_cal_due': values.get('module_cal_due'),
        'inst_software_version': values.get('software_version'),
        'inst_scanner_type': values.get('scanner_type'),
        'inst_scanner_model': values.get('scanner_model'),
        'inst_analysis_software': values.get('analysis_software'),
        'inst_analysis_software_version': values.get('analysis_software_version'),
        'inst_encoder_cal': scan_encoder(values.get('encoder_resolution')),
        'inst_scan_res': with_unit(values.get('x_res'), length),
        'inst_scan_speed': values.get('scan_speed'),
    }
    probe = {
        'kind': kind(values),
        'make': values.get('manufacturer'),
        'model': values.get('transducer_model'),
        'frequency': with_unit(values.get('freq'), ' MHz'),
        'cable_type': values.get('cable_type'),
        'cable_length': values.get('cable_length'),
        'serial': values.get('transducer_serial'),
        'wedge_material': values.get('wedge_material'),
        'wedge_model': values.get('wedge_model'),
        'wedge_angle': with_unit(values.get('wedge_angle'), '°'),
        'wedge_diameter': with_unit(values.get('specimen_od'), length),
        'wedge_curve': values.get('wedge_curve'),
        'catalogue_probe': values.get('catalogue_probe'),
        'catalogue_wedge': values.get('catalogue_wedge'),
        'wedge_primary_offset': values.get('wedge_primary_offset'),
        'wedge_first_element_height': values.get('wedge_first_element_height'),
        'wedge_velocity': values.get('wedge_velocity'),
        'wedge_length': values.get('wedge_length'),
        'wedge_height': values.get('wedge_height'),
        'source_file': values.get('source_file'),
    }
    group = {
        'scan': values.get('beam_formation'),
        'wave_mode': values.get('wave_propagation'),
        'angles': values.get('angle_range'),
        'elements': values.get('active_elements'),
        'angle_increment': with_unit(values.get('angle_step'), '°'),
        'vpa': _vpa(values),
        'focal_plane': values.get('focal_plane'),
        'focal_distance': with_unit(values.get('foc_depth'), length),
        'time_base': values.get('time_base'),
        'voltage': with_unit(values.get('voltage'), ' V'),
        'points_quantity': values.get('points_quantity'),
        'smoothing': values.get('smoothing'),
        'filter': with_unit(values.get('band_pass_filter'), ' MHz'),
        'amplitude_range': values.get('amplitude_range'),
        'reference_db': with_unit(values.get('gain'), ' dB'),
        'transfer_db': values.get('transfer_db'),
        'scanning_db': values.get('scanning_db'),
        'first_element': values.get('first_element'),
        'aperture_elements': values.get('aperture_elements'),
        'source_file': values.get('source_file'),
    }

    def kept(fields):
        return {k: _s(v) for k, v in fields.items() if _s(v)}

    probe = kept(probe)
    return {'instrument': kept(instrument), 'probe': probe, 'group': kept(group), 'probe_key': probe_key(probe)}
