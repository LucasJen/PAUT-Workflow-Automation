# Seeds the text library with the standard texts from the HIC reference report
# (2026-08-PAUT-HIC_LVLA-15V3). They can be edited in the app's Text library.

from django.db import migrations

TECHNIQUES = [
    ('HydroFORM', 'ENCODED HydroFORM 0-degree PAUT',
     'HydroFORM utilizes a PAUT transducer with a water-column and consumable gasket to allow for a PAUT '
     'immersion inspection with a low-flow water supply. Synchronized gates in the software and no need for '
     'contact wedges allows for better coupling, near surface resolution, and more precise measurements as '
     'compared to traditional contact UT scanning.'),
    ('Angle Beam', 'PAUT Angle Beam',
     'PAUT transducers contain an array of elements which are pulsed at desired time delays to steer and focus '
     'the sound beam utilizing constructive wave interference. Sectorial scans are setup up with a range of '
     'angles (e.g., 40°-73°) which are displayed on the sectorial image allowing for excellent flaw detection, '
     'characterizing, and height sizing abilities when compared to conventional shear wave inspection.'),
    ('TFM', 'Total Focusing Method (TFM)',
     'The Total Focusing Method uses the Full Matrix Capture (FMC) method of collecting phased array data where '
     'each element of the PAUT probe is activated one by one. The signal from each element is received by all '
     'elements and stored in order, from which a matrix of signal data is stored. The data is then processed '
     'through the TFM algorithm which optimally focuses on every point in a Region of Interest (ROI). The TFM '
     'imaging allows for improved signal characterization over a larger area when compared to PAUT.'),
]

DISCUSSION = (
    'In the Results section, a table has been constructed to generalize the analysis of each scan location. '
    'Images will also be included for the analysis, which includes the detection corrosion or cracking, if any, '
    'along with a comment column used for explaining trends or making general comments. Each scan image provides '
    'a C-scan (top view), B-scan (side view), D-scan (end view) and A-scan (reflected sound amplitude vs time). '
    'The crosshairs are placed on the minimum thickness, or the largest indication observed in the scan area.'
)


def seed(apps, schema_editor):
    TextSnippet = apps.get_model('reports', 'TextSnippet')
    for name, title, body in TECHNIQUES:
        TextSnippet.objects.get_or_create(kind='technique', name=name, defaults={'title': title, 'body': body})
    TextSnippet.objects.get_or_create(kind='discussion', name='default', defaults={'title': '', 'body': DISCUSSION})


def unseed(apps, schema_editor):
    TextSnippet = apps.get_model('reports', 'TextSnippet')
    TextSnippet.objects.filter(kind='technique', name__in=[n for n, _, _ in TECHNIQUES]).delete()
    TextSnippet.objects.filter(kind='discussion', name='default').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0020_prose_fields_text_library'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
