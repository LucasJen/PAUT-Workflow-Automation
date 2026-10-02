"""
Defaults hold prefilled probe / group columns (lists) instead of one set of starting values for
every new column; probe and group columns record the file that filled them.
"""
from django.db import migrations, models


def values_to_columns(apps, schema_editor):
    ReportDefaults = apps.get_model('reports', 'ReportDefaults')
    for item in ReportDefaults.objects.all():
        item.probe_columns = [item.probe_values] if item.probe_values else []
        item.group_columns = [{**item.group_values, 'probe_column': '0'} if item.probe_values else item.group_values] \
            if item.group_values else []
        item.save(update_fields=['probe_columns', 'group_columns'])


def mark_converted_columns(apps, schema_editor):
    """Columns 0037 made from a report's setups were filled from them: an import adds new ones."""
    Report = apps.get_model('reports', 'Report')
    for report in Report.objects.filter(report_type='paut_weld'):
        setups = list(report.setups.order_by('order', 'pk'))
        for model in (apps.get_model('reports', 'ReportProbe'), apps.get_model('reports', 'ReportGroup')):
            columns = list(model.objects.filter(report=report).order_by('order', 'pk'))
            if len(columns) != len(setups):
                continue
            for column, setup in zip(columns, setups):
                column.source_file = setup.source_file or f'Setup #{setup.pk}'
                column.save(update_fields=['source_file'])


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0038_defaults_grid_columns'),
    ]

    operations = [
        migrations.AddField('reportdefaults', 'probe_columns', models.JSONField(blank=True, default=list)),
        migrations.AddField('reportdefaults', 'group_columns', models.JSONField(blank=True, default=list)),
        migrations.RunPython(values_to_columns, migrations.RunPython.noop),
        migrations.RemoveField('reportdefaults', 'probe_values'),
        migrations.RemoveField('reportdefaults', 'group_values'),
        migrations.AddField('reportprobe', 'source_file', models.CharField(blank=True, max_length=255)),
        migrations.AddField('reportgroup', 'source_file', models.CharField(blank=True, max_length=255)),
        migrations.RunPython(mark_converted_columns, migrations.RunPython.noop),
    ]
