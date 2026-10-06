"""
Scan plans: 'Sides' becomes 90 / 270 deg skew checkboxes at the index offset, plus an optional
second index offset with its own skews. 'Both sides' -> 90 and 270; 'One side' -> 90 only.
"""
from django.db import migrations, models


def sides_to_skews(apps, schema_editor):
    ScanPlan = apps.get_model('reports', 'ScanPlan')
    ScanPlan.objects.filter(sides='one').update(skew_90=True, skew_270=False)
    ScanPlan.objects.exclude(sides='one').update(skew_90=True, skew_270=True)


def skews_to_sides(apps, schema_editor):
    ScanPlan = apps.get_model('reports', 'ScanPlan')
    ScanPlan.objects.filter(skew_270=False).update(sides='one')
    ScanPlan.objects.filter(skew_270=True).update(sides='both')


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0031_nde_wedge_size'),
    ]

    operations = [
        migrations.AddField(model_name='scanplan', name='skew_90', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='scanplan', name='skew_270', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='scanplan', name='index_offset_2',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='scanplan', name='skew_90_2', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='scanplan', name='skew_270_2', field=models.BooleanField(default=False)),
        migrations.RunPython(sides_to_skews, skews_to_sides),
        migrations.RemoveField(model_name='scanplan', name='sides'),
    ]
