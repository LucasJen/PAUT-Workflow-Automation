"""
The SA1-N60S seed took its first element height (0.330 in = 8.382 mm) from an OmniScan setup
export, which measures it differently from the wedge geometry the scan plan uses (Beamtool's
SA1-N60S 10L32 has 5.15 mm). Clears it, only where it still holds the seeded value.
"""
from django.db import migrations


def clear(apps, schema_editor):
    WedgeModel = apps.get_model('equipment', 'WedgeModel')
    WedgeModel.objects.filter(model='SA1-N60S', first_element_height=8.382, primary_offset=None).update(
        first_element_height=None,
        notes='Wedge angle from the OmniScan setup of PPI-31-37575 (38.90°). For the scan plan, use the '
              'probe-specific entries from the Beamtool library (e.g. SA1-N60S 10L32).',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('equipment', '0007_wedge_library_fields'),
    ]

    operations = [
        migrations.RunPython(clear, migrations.RunPython.noop),
    ]
