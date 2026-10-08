"""
Guided Creation for the corrosion form (598-PAUTFORM-009): a job folder's .nde files (optional,
a manual UT job has none) become the report's setups, and its pictures its drawings, setup images
and Images pages. read_corrosion_file() reads one .nde; build_corrosion_report() makes the report.
"""
import os
import re

from django.core.files import File
from django.db import transaction

from equipment.inventory import with_library_scope

from ..models import Report, ReportImage, Setup, SetupImage
from .job_folder import PICTURE_EXTENSIONS
from .job_import import catalogue_match, scope_label
from .nde_parser import NdeError, extract_groups, read_nde

CORROSION_TYPE = 'paut_corrosion'
# What a folder picture is used for
DRAWING, SETUP, IMAGE, SKIP = 'drawing', 'setup', 'image', 'skip'
ROLE_CHOICES = [(DRAWING, 'Drawing'), (SETUP, 'Setup image'), (IMAGE, 'Image'), (SKIP, 'Leave out')]
SETUP_FIELDS = {f.name for f in Setup._meta.concrete_fields} - {'id', 'report', 'order'}


def method_of(values):
    """The corrosion form's method for an .nde group: HydroFORM by its wedge / scanner, else PAUT Angle Beam
    for an angled beam; '' when it can't tell (e.g. a 0 degree contact scan)."""
    hardware = f"{values.get('wedge_model', '')} {values.get('scanner_model', '')}".lower()
    if 'hydroform' in hardware:
        return 'HydroFORM'
    if values.get('wave_propagation') == 'Shear':
        return 'PAUT Angle Beam'
    return ''


def read_corrosion_file(uploaded, system='imperial'):
    """One .nde of the job: {'filename', 'scan_time', 'setups': [{'label', 'method', 'values'}], 'scope'} or
    {'filename', 'error'}."""
    try:
        setup, properties = read_nde(uploaded)
    except NdeError as e:
        return {'filename': uploaded.name, 'error': str(e)}
    setups, scope = [], None
    for group in extract_groups(setup, properties, uploaded.name):
        fill, _ = catalogue_match(group.get('hardware', {}))
        values, scope = with_library_scope({**group['values'][system], **fill})
        values = {k: v for k, v in values.items() if k in SETUP_FIELDS and v not in (None, '')}
        method = method_of(values)
        values['title'] = method or values.get('title', '')
        setups.append({'label': group['label'], 'method': method, 'values': values})
    if not setups:
        return {'filename': uploaded.name, 'error': 'No inspection groups in this file.'}
    first = setups[0]['values']
    return {'filename': uploaded.name, 'scan_time': first.get('acquisition_date', ''), 'setups': setups,
            'scope': scope_label(scope)}


def setup_key(values):
    """Files scanned with the same technique, probe and instrument share one setup page."""
    return tuple(values.get(k, '') for k in ('title', 'transducer_model', 'transducer_serial', 'scope_serial',
                                               'wedge_model'))


def distinct_setups(files):
    """The setups of the job's files, one per technique / probe / instrument, in file order."""
    seen = {}
    for data in files:
        if data.get('error'):
            continue
        for item in data['setups']:
            seen.setdefault(setup_key(item['values']), item['values'])
    return list(seen.values())


def folder_pictures(folder):
    """The folder's pictures (top level), by name."""
    try:
        names = sorted(n for n in os.listdir(folder)
                       if os.path.splitext(n)[1].lower() in PICTURE_EXTENSIONS and os.path.isfile(os.path.join(folder, n)))
    except OSError:
        return []
    return sorted(names, key=str.lower)


def guess_role(name):
    """A first guess at what a folder picture is: a photo / scan of the drawing (.jpg), an instrument
    screenshot (setup image), else a scan image for the Images pages."""
    lower = name.lower()
    if 'screenshot' in lower:
        return SETUP
    if os.path.splitext(lower)[1] in ('.jpg', '.jpeg') or re.search(r'drawing|model|layout|iso', lower):
        return DRAWING
    return IMAGE


def caption_for(name):
    """'strip scan top head.png' -> 'Strip scan top head'."""
    stem = re.sub(r'[_]+', ' ', os.path.splitext(name)[0]).strip()
    return stem[:1].upper() + stem[1:]


def equipment_from_folder(name):
    """'11V58A Corrosion Scan' -> '11V58A'; '86TK116 Corrosion Scans' -> '86TK116'."""
    return (name or '').strip().split(' ')[0] if name else ''


def _attach(file_field, path):
    with open(path, 'rb') as f:
        file_field.save(os.path.basename(path), File(f), save=False)


@transaction.atomic
def build_corrosion_report(files, pictures, defaults=None, document_filename='', equipment_id='', job_folder='',
                           client=None):
    """
    The corrosion report for the job: `files` from read_corrosion_file (errors left out), `pictures`
    [(path, role, caption)], starting from a defaults set. Returns (report, notes).
    """
    from .job_import import _set_report_values   # the weld import's way of applying a defaults set
    notes = []
    report = Report(report_type=CORROSION_TYPE)
    if defaults is not None:
        _set_report_values(report, defaults.report_values)
    report.document_filename = document_filename or report.document_filename
    report.equipment_id = equipment_id or report.equipment_id
    report.job_folder = str(job_folder or '')
    if client is not None:
        report.client = client.client
        report.location = client.location or report.location
    dates = sorted(d['scan_time'][:10] for d in files if not d.get('error') and d.get('scan_time'))
    if dates:
        report.test_date = dates[0]
    report.save()

    setup_defaults = (defaults.setup_values or {}) if defaults is not None else {}
    found = distinct_setups(files)
    setups = []
    for i, values in enumerate(found or [{}]):
        setup = Setup(report=report, order=i)
        for name, value in {**{k: v for k, v in setup_defaults.items() if k in SETUP_FIELDS}, **values}.items():
            if name in ('catalogue_probe', 'catalogue_wedge'):   # catalogue matches come as primary keys
                setattr(setup, f'{name}_id', int(value) if str(value).isdigit() else None)
            else:
                setattr(setup, name, value)
        setup.save()
        setups.append(setup)
    if not found:
        notes.append('No .nde files: one empty setup was added for the setup page; fill in its method and equipment.')

    setup_pictures = [p for p in pictures if p[1] == SETUP]
    for i, (path, _, _) in enumerate(setup_pictures):
        image = SetupImage(setup=setups[min(i, len(setups) - 1)], order=i)
        _attach(image.image, path)
        image.save()
    order = 0
    for path, role, caption in pictures:
        if role not in (DRAWING, IMAGE):
            continue
        image = ReportImage(report=report, kind=ReportImage.DRAWING if role == DRAWING else ReportImage.SCAN,
                            caption=caption if role == IMAGE else '', order=order)
        _attach(image.image, path)
        image.save()
        order += 1
    return report, notes
