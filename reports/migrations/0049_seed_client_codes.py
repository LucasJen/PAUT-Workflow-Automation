from django.db import migrations


def seed(apps, schema_editor):
    # The client the app's reports so far are for; PPI's name is added in Library › Client codes
    ClientCode = apps.get_model('reports', 'ClientCode')
    ClientCode.objects.get_or_create(code='FHR', defaults={'client': 'Flint Hills Resources',
                                                           'location': 'Rosemount, MN'})


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0048_job_folders'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
