"""
manage.py link_setup_catalogue [--dry-run]

Links saved setups that have no catalogue probe / wedge yet to the catalogue, from their text
fields (probe model, wedge model and angle, active elements). Setups imported from an .nde file
from now on are matched on import, with the file's full wedge geometry.
"""
import re

from django.core.management.base import BaseCommand

from equipment.matching import match_probe, match_wedge
from reports.models import Setup

NUMBER = re.compile(r'\d+(?:\.\d+)?')


def _number(text):
    match = NUMBER.search(text or '')
    return float(match.group()) if match else None


def _elements(active):
    """(first element, aperture) from '1–27'."""
    numbers = [int(float(n)) for n in NUMBER.findall(active or '')]
    if len(numbers) >= 2 and numbers[1] >= numbers[0]:
        return numbers[0], numbers[1] - numbers[0] + 1
    return None, None


class Command(BaseCommand):
    help = 'Links saved setups to the probe / wedge catalogue from their probe and wedge names.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be linked without saving.')

    def handle(self, *args, dry_run=False, **options):
        linked, unmatched = 0, []
        for setup in Setup.objects.filter(catalogue_probe=None, catalogue_wedge=None).exclude(transducer_model=''):
            model = setup.transducer_model.strip()
            series = re.search(r'-([A-Z]{1,4}\d{1,3})$', model)
            probe = match_probe({'model': model, 'series': series.group(1) if series else '',
                                 'frequency': _number(setup.freq), 'elements': int(_number(setup.elements) or 0) or None})
            wedge = match_wedge({'model': setup.wedge_model.strip(), 'wedge_angle': _number(setup.wedge_angle)},
                                probe.item) if setup.wedge_model.strip() else None
            if probe.item is None and (wedge is None or wedge.item is None):
                unmatched.append(f'#{setup.pk} {model} / {setup.wedge_model or "no wedge"}')
                continue
            setup.catalogue_probe = probe.item
            setup.catalogue_wedge = wedge.item if wedge else None
            if setup.first_element is None:
                setup.first_element, setup.aperture_elements = _elements(setup.active_elements)
            wedge_text = f'{wedge.item} ({wedge.how})' if wedge and wedge.item else 'no wedge'
            if wedge and wedge.suggestion is not None:
                wedge_text += f'; geometry matches {wedge.suggestion}'
            self.stdout.write(f'Setup #{setup.pk}: {probe.item or "no probe"} ({probe.how or "-"}), {wedge_text}')
            if not dry_run:
                setup.save(update_fields=['catalogue_probe', 'catalogue_wedge', 'first_element', 'aperture_elements'])
            linked += 1
        self.stdout.write(f'{"Would link" if dry_run else "Linked"} {linked} setup(s).')
        if unmatched:
            self.stdout.write('No catalogue match: ' + '; '.join(unmatched))
