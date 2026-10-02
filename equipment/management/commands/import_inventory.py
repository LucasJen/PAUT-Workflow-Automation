"""
Fills the scope and probe inventory from a weld report workbook's "Scope and Encoder" and
"All Probes 2025" sheets (see equipment/inventory.py), e.g.

    manage.py import_inventory "outputs/PPI-31-37575-W5&W6-6inch.xlsx"

Scopes and probes already in the inventory (same serial number) are updated; --dry-run lists
what the workbook holds without saving.
"""
from django.core.management.base import BaseCommand, CommandError

from equipment.inventory import InventoryError, apply_inventory, read_probes, read_scopes


class Command(BaseCommand):
    help = "Fills the scope and probe inventory from a weld report workbook's equipment sheets."

    def add_arguments(self, parser):
        parser.add_argument('workbook', help='The .xlsx weld report (100-UTFORM-010) to read.')
        parser.add_argument('--dry-run', action='store_true', help='List what would be imported; save nothing.')

    def handle(self, workbook, dry_run=False, **options):
        try:
            scopes, probes = read_scopes(workbook), read_probes(workbook)
        except InventoryError as e:
            raise CommandError(str(e))
        if dry_run:
            for scope in scopes:
                self.stdout.write(f"Scope  {scope['name']}  {scope['serial_number']}  due {scope['calibration_due_date']}")
            for probe in probes:
                self.stdout.write(f"Probe  {probe['model']}  {probe['serial_number']}")
            self.stdout.write(f'{len(scopes)} scopes, {len(probes)} probes (dry run, nothing saved).')
            return
        counts = apply_inventory(scopes, probes)
        self.stdout.write(self.style.SUCCESS(', '.join(f'{n} {what}' for what, n in counts.items())))
