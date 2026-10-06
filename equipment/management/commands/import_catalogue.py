"""
manage.py import_catalogue PATransducers.csv PAWedges.csv [scan.nde ...] [--series A1,A2,A10,A15,A31,A32]
"""
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from equipment.importers import CatalogueImportError, apply_catalogue, read_catalogue_file


class Command(BaseCommand):
    help = ('Adds or updates the probe and wedge catalogues from Beamtool library exports '
            '(PATransducers.csv, PAWedges.csv) or OmniScan .nde files.')

    def add_arguments(self, parser):
        parser.add_argument('files', nargs='+')
        parser.add_argument('--series', default='',
                            help='Only import probes and wedges of these probe series, e.g. A1,A2,A10,A15,A31,A32.')

    def handle(self, *args, files, series, **options):
        keep = {s.strip().lower() for s in series.split(',') if s.strip()}
        probes, wedges = [], []
        for path in files:
            try:
                with open(path, 'rb') as f:
                    uploaded = SimpleUploadedFile(os.path.basename(path), f.read())
                found_probes, found_wedges = read_catalogue_file(uploaded)
            except (OSError, CatalogueImportError) as e:
                raise CommandError(f'{path}: {e}') from e
            probes += found_probes
            wedges += found_wedges
        if keep:
            probes = [p for p in probes if (p.get('series') or '').lower() in keep]
            wedges = [w for w in wedges if (w.get('probe_series') or '').lower() in keep]
        self.stdout.write(apply_catalogue(probes, wedges) or 'Nothing to import.')
