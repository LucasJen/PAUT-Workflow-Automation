"""
Seeds the probe and wedge catalogues (Evident catalogue data) and the sensitivity block table
(the reference weld report's Cal Block Table) from equipment/seed/*.json. Existing entries
with the same model / pipe size are left as they are.
"""
import json
from pathlib import Path

from django.db import migrations

SEED = Path(__file__).resolve().parent.parent / 'seed'


def _load(name):
    return json.loads((SEED / name).read_text(encoding='utf-8'))


def seed(apps, schema_editor):
    ProbeModel = apps.get_model('equipment', 'ProbeModel')
    WedgeModel = apps.get_model('equipment', 'WedgeModel')
    SensitivityBlock = apps.get_model('equipment', 'SensitivityBlock')
    for row in _load('probe_models.json'):
        ProbeModel.objects.get_or_create(model=row.pop('model'), defaults=row)
    for row in _load('wedge_models.json'):
        WedgeModel.objects.get_or_create(model=row.pop('model'), defaults=row)
    for row in _load('sensitivity_blocks.json'):
        if not SensitivityBlock.objects.filter(pipe_size=row['pipe_size']).exists():
            SensitivityBlock.objects.create(**row)


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0005_catalogues_and_block_table'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
