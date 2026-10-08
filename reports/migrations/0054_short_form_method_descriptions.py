"""
Seeds the Text library with the method descriptions of the Short Form's Formulas sheet
(598-PAUTFORM-009), which its setup pages now pick from (Setup.method_description). A name the
library already has gets ' (Short Form)' added, so existing (Long Form) descriptions are kept.
"""
from django.db import migrations

# (name, bold lead, text) from excel_templates/paut_corrosion.xlsx › Formulas
DESCRIPTIONS = (
    ('PAUT Angle Beam',
     'Phased Array (PAUT) Angle Beam',
     'PAUT angle beam is an advanced ultrasonic technique that utilizes a transducer which contains an array of elements which are pulsed at desired time delays to steer and focus the sound beam using constructive wave interference for multi-angle imaging. Sectoral scan imaging displays a range of angles (e.g. 40°-70°) which allows for excellent flaw detection and characterizing when compared to conventional shear wave.'),
    ('HydroFORM',
     'HydroFORM',
     'HydroFORM utilizes a multi-element array transducer with a water-column and consumable gasket to allow for a ultrasonic phased array immersion inspection with a low-flow water supply. Synchronized gates in the software and no need for contact wedges allows for better coupling, near surface resolution, and more precise measurements as compared to traditional contact UT scanning.'),
    ('UT Shear Wave',
     'UT-Shear Wave (UTSW)',
     'UTSW is a conventional ultrasonic technique which transmits ultrasound through the examination material with a single element transducer using a wedge at a pre-determined angle and typically has a small physical footprint. Shear wave UT is commonly used with the purpose of weld-quality or crack examination.'),
    ('AUT',
     'Automated Ultrasonic Testing (AUT)',
     'AUT is a technique that utilizes an automated scanner, which compiles and encodes ultrasonic thickness measurements to create B & C-Scan imaging. This is done with software on a cartesian X-Y coordinate grid system and is advantageous for large area scanning.'),
    ('Manual UT',
     'Manual Ultrasonic Testing (MUT)',
     'MUT is a conventional ultrasonic technique which utilizes a single element transducer to transmit ultrasound through the examination material at a 0˚ angle with a contact transducer by hand, most commonly with the purpose of thickness measurements or lamination detection.'),
    ('TOFD',
     'Time of Flight Diffraction (TOFD)',
     'TOFD is an ultrasonic technique which utilizes the “pitch-catch” method, where one transducer transmits ultrasonic waves while the second transducer receives them. TOFD works on the principle of initially pulsing sound into and ‘flooding’ the area of interest (using a low angle of incidence and a small diameter transducer). Once the ultrasonic waves hit a defect, it will vibrate, and diffraction signals are generated from the defect tip(s). The receiving probe measures and plots the “Time of Flight” of all signals that reach it, including the diffracted signal from the flaw(s).'),
    ('PCI',
     'Phase Coherence Imaging (PCI)',
     'A technique which utilizes a method of compiling data called Full Matrix Capture (FMC) to improve resolution and contrast in ultrasonic testing imaging. PCI is designed for materials that present a low signal to noise ratio such as coarse-grained material like Stainless Steel and Inconel. It is based on evaluating the coherence between the signals detected by each separate element of a phased array multi-element transducer and color coding the image display by percentage of coherence (number of elements that receive the same signal in the same location) instead of by amplitude. This type of imaging helps to define low amplitude relevant signals in a “noisy” signal environment.'),
    ('FMC / TFM',
     'Total Focusing Method (TFM)',
     'The Total Focusing Method uses the Full Matrix Capture method of collecting phased array data where each element of the PAUT probe is singly activated one by one. The signal from each element is received by all other elements and stored as A-scans in order, from which a matrix of signal data is processed and constructed. This technique of sending and receiving sound waves allows for synthetic focusing at every point within the region of interest to enable enhanced resolution'),
)


def seed(apps, schema_editor):
    TextSnippet = apps.get_model('reports', 'TextSnippet')
    for name, title, body in DESCRIPTIONS:
        if TextSnippet.objects.filter(kind='technique', name=name, body=body).exists():
            continue
        if TextSnippet.objects.filter(kind='technique', name=name).exists():
            name = f'{name} (Short Form)'
        TextSnippet.objects.get_or_create(kind='technique', name=name, defaults={'title': title, 'body': body})


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0053_setup_method_description'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
