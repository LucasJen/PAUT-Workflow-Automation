"""
The validation from the command line, the same as the Validation page:
    manage.py validate run [--layers L0,L1] [--kit PATH] [--sweep [FOLDER]]
    manage.py validate add FILE --roles decoding,readings [--source "..."] [--notes "..."] [--kit PATH]
    manage.py validate import EXPORT --nde KIT_PATH [--source "..."] [--kit PATH]   (an OmniPC export)
    manage.py validate import-setups [FOLDER] [--in-place] [--kit PATH]   (every export with a setup.csv beside its .nde)
    manage.py validate check [--kit PATH]          (fingerprints only)
The run is saved like one started on the page, and shows there.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from validation import importer, runner
from validation.kit import ROLES, Kit, KitError
from validation.models import ValidationSettings


class Command(BaseCommand):
    help = 'Validate the Analysis page against the validation kit (raw data, OmniPC, calibration blocks).'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        run = sub.add_parser('run', help='Run the validation.')
        run.add_argument('--layers', default='', help='Comma-separated layer ids (default: all).')
        run.add_argument('--approve', default=None, metavar='NOTE',
                         help='Lock the current results as the approved baseline (L6), with a note of who and why.')
        run.add_argument('--sweep', nargs='?', const=runner.default_sweep(), default=None,
                         help='Also decode every .nde file under this folder (default: the Reports folder).')
        add = sub.add_parser('add', help='Add a file to the kit (copied in, fingerprinted).')
        add.add_argument('file')
        add.add_argument('--roles', required=True, help=f"Comma-separated: {', '.join(ROLES)}")
        add.add_argument('--source', default='', help='Where it came from (e.g. "OmniPC 5.12 export, 2026-10-09").')
        add.add_argument('--notes', default='')
        imp = sub.add_parser('import', help='Import an OmniPC export (zip or indications.csv) as readings points.')
        imp.add_argument('export')
        imp.add_argument('--nde', required=True, help="The kit path of the .nde file it was made from, e.g. 'nde/x.nde'.")
        imp.add_argument('--source', default='')
        imp.add_argument('--sized', action='store_true', help="The cursors were put on the -6 dB ends (S(r) / S(m) exported): L2 sizing.")
        imp.add_argument('--complete', action='store_true', help='The export lists every indication in the file: L2 detection.')
        setups = sub.add_parser('import-setups', help="Every OmniPC export with a setup.csv under a folder, with the .nde beside it.")
        setups.add_argument('folder', nargs='?', default=runner.default_sweep())
        setups.add_argument('--in-place', action='store_true', help='List the .nde files where they are instead of copying them into the kit.')
        sub.add_parser('check', help="Check the kit's fingerprints.")
        for p in (run, add, imp, setups, sub.choices['check']):
            p.add_argument('--kit', default=None, help='The kit folder (default: the one set on the Validation page).')

    def handle(self, action, kit=None, **options):
        path = kit or ValidationSettings.get().kit
        try:
            if action == 'add':
                entry = Kit(path).add(options['file'], [r.strip() for r in options['roles'].split(',') if r.strip()],
                                      options['source'], options['notes'])
                self.stdout.write(f"Added {entry['path']} ({entry['sha256'][:12]}…)")
            elif action == 'import':
                k = Kit(path)
                nde = next((e for e in k.nde_files() if e['path'] == options['nde'].replace(os.sep, '/')), None)
                if nde is None:
                    raise CommandError(f"{options['nde']} isn't an .nde file in the kit.")
                for entry in importer.import_export(k, options['export'], nde, options['source'],
                                                    sizing='6' if options['sized'] else None, complete=options['complete']):
                    self.stdout.write(f"Imported {entry['path']}: {entry['notes']}")
            elif action == 'import-setups':
                self.import_setups(Kit(path), options['folder'], not options['in_place'])
            elif action == 'check':
                for c in Kit(path).verify():
                    self.stdout.write(f"{'ok  ' if c['ok'] else 'FAIL' if c['ok'] is False else 'away'} {c['path']} {c['reason']}")
            else:
                layers = [x.strip().upper() for x in options['layers'].split(',') if x.strip()]
                extra = {'sweep': os.path.abspath(options['sweep'])} if options['sweep'] else {}
                if options['approve']:
                    layers, extra = ['L6'], {'approve': options['approve']}
                run = runner.create(layers, path, extra)
                self.stdout.write(f'Run {run.pk} at {run.version} on {path}')
                runner.execute(run)
                self._print(run)
        except (KitError, importer.ImportError_) as e:
            raise CommandError(str(e)) from e

    def import_setups(self, kit, folder, copy):
        import glob
        import zipfile
        added = 0
        for z in sorted(glob.glob(os.path.join(folder, '**', '*.zip'), recursive=True)):
            try:
                with zipfile.ZipFile(z) as f:
                    if not any(os.path.basename(n).lower() == 'setup.csv' for n in f.namelist()):
                        continue
            except (zipfile.BadZipFile, OSError):
                continue
            stem = os.path.basename(z)[:-4].lower()
            ndes = [n for n in glob.glob(os.path.join(os.path.dirname(z), '*.nde'))
                    if stem.startswith(os.path.splitext(os.path.basename(n))[0].lower().strip())]
            if not ndes:
                self.stdout.write(f'  no .nde beside {z}')
                continue
            nde = max(ndes, key=lambda n: len(os.path.basename(n)))
            entry = next((e for e in kit.nde_files() if os.path.normcase(kit.full_path(e)) == os.path.normcase(os.path.abspath(nde))), None) \
                or kit.add(nde, ['decoding'], f'Job scan ({os.path.relpath(os.path.dirname(nde), folder)})', copy=copy)
            setup = importer.import_setup(kit, z, entry, 'OmniPC export from the job folder', copy=copy)
            self.stdout.write(f"Added {os.path.basename(nde)} with {setup['notes']}")
            added += 1
        self.stdout.write(f'{added} setups added.')

    def _print(self, run):
        r = run.results
        self.stdout.write(f"Kit: {r['kit'].get('message', r['kit'].get('status'))}")
        for c in r['kit'].get('files') or []:
            if c['ok'] is False:
                self.stdout.write(f"  FAIL {c['path']}: {c['reason']}")
        for layer in r['layers']:
            self.stdout.write(f"{layer['id']} {layer['title']}: {layer['status']} - {layer['message']}")
            for c in layer['checks']:
                if c['kind'] == 'check' and not c['passed']:
                    self.stdout.write(f"  FAIL {c['subject']}")
                    for i in c['items']:
                        if i['ok'] is False:
                            self.stdout.write(f"       {i['what']}: expected {i['expected']}, measured {i['measured']} ({i['rule']})")
        if r.get('error'):
            self.stdout.write(f"Error: {r['error']}")
        self.stdout.write(f'{run.status.upper()}: {run.passed} passed, {run.failed} failed')
