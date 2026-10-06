"""
Existing weld reports: each setup becomes a probe column and a group column of the equipment
grid, and the first setup's instrument fills the report's testing instrument. The setups are
left as they are. Values are written as the weld form showed them (units added).
"""
import re

from django.db import migrations

NUMBER = re.compile(r'^-?\d+(\.\d+)?$')


def with_unit(value, unit):
    value = (value or '').strip()
    return f'{value}{unit}' if NUMBER.match(value) else value


def length_unit(setup):
    return ' mm' if getattr(setup, 'units', 'imperial') == 'metric' else '"'


def vpa(setup):
    if 'sector' in (setup.beam_formation or '').lower() or not (setup.element_aperture and setup.element_step):
        return 'N/A'
    return f'{setup.element_aperture} ele / {setup.element_step} ele'


def kind(setup):
    if (setup.beam_formation or '').strip().lower() != 'conventional':
        return 'paut'
    return 'conv_long' if (setup.wave_propagation or '').strip() == 'Longitudinal' else 'conv_shear'


def setups_to_grid(apps, schema_editor):
    Report = apps.get_model('reports', 'Report')
    ReportProbe = apps.get_model('reports', 'ReportProbe')
    ReportGroup = apps.get_model('reports', 'ReportGroup')
    for report in Report.objects.filter(report_type='paut_weld'):
        if ReportProbe.objects.filter(report=report).exists():
            continue
        setups = list(report.setups.order_by('order', 'pk'))
        for i, s in enumerate(setups):
            probe = ReportProbe.objects.create(
                report=report, order=i, kind=kind(s), make=s.manufacturer or '', model=s.transducer_model or '',
                frequency=with_unit(s.freq, ' MHz'), cable_type=s.cable_type, cable_length=s.cable_length,
                serial=s.transducer_serial or '', wedge_material=s.wedge_material, wedge_model=s.wedge_model or '',
                wedge_angle=with_unit(s.wedge_angle, '°'), wedge_diameter=with_unit(s.specimen_od, length_unit(s)),
                wedge_curve=s.wedge_curve, probe_check='Accept',
                catalogue_probe_id=s.catalogue_probe_id, catalogue_wedge_id=s.catalogue_wedge_id,
                wedge_primary_offset=s.wedge_primary_offset, wedge_first_element_height=s.wedge_first_element_height,
                wedge_velocity=s.wedge_velocity, wedge_length=s.wedge_length, wedge_height=s.wedge_height,
            )
            ReportGroup.objects.create(
                report=report, order=i, probe=probe, scan=s.beam_formation or '', wave_mode=s.wave_propagation or '',
                angles=s.angle_range or '', elements=s.active_elements or '',
                angle_increment=with_unit(s.angle_step, '°'), vpa=vpa(s), focal_plane=s.focal_plane,
                focal_distance=with_unit(s.foc_depth, length_unit(s)), time_base=s.time_base,
                voltage=with_unit(s.voltage, ' V'), points_quantity=s.points_quantity, smoothing=s.smoothing,
                filter=with_unit(s.band_pass_filter, ' MHz'), amplitude_range=s.amplitude_range,
                reference_db=with_unit(s.gain, ' dB'), transfer_db=s.transfer_db, scanning_db=s.scanning_db,
                first_element=s.first_element, aperture_elements=s.aperture_elements,
            )
        if setups:
            s = setups[0]
            report.inst_name = s.scope_platform or s.scope_model or ''
            report.inst_manufacturer = s.manufacturer or ''
            report.inst_model = s.scope_model or ''
            report.inst_serial = s.scope_serial or ''
            report.inst_cal_due = s.scope_cal_due
            report.inst_module_model = s.module_model
            report.inst_module_serial = s.module_serial
            report.inst_module_cal_due = s.module_cal_due
            report.inst_software_version = s.software_version
            report.inst_scanner_type = s.scanner_type
            report.inst_scanner_model = s.scanner_model
            report.inst_analysis_software = s.analysis_software
            report.inst_analysis_software_version = s.analysis_software_version
            report.inst_encoder_cal = s.encoder_resolution or ''
            report.inst_scan_res = with_unit(s.x_res, length_unit(s))
            report.inst_scan_speed = s.scan_speed
            report.save()


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0036_weld_equipment_grid'),
    ]

    operations = [
        migrations.RunPython(setups_to_grid, migrations.RunPython.noop),
    ]
