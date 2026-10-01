"""manage.py import_catalogue PATransducers.csv PAWedges.csv [scan.nde ...]"""
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError

from equipment.importers import CatalogueImportError, apply_catalogue, read_catalogue_file


class Command(BaseCommand):
    help = ('Adds or updates the probe and wedge catalogues from Beamtool library exports '
            '(PATransducers.csv, PAWedges.csv) or OmniScan .nde files.')

    def add_arguments(self, parser):
        parser.add_argument('files', nargs='+')

    def handle(self, *args, files, **options):
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
        self.stdout.write(apply_catalogue(probes, wedges) or 'Nothing to import.')
