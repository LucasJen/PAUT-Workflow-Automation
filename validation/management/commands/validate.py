"""
The validation from the command line, the same as the Validation page:
    manage.py validate run [--layers L0,L1] [--kit PATH] [--sweep [FOLDER]]
    manage.py validate add FILE --roles decoding,readings [--source "..."] [--notes "..."] [--kit PATH]
    manage.py validate check [--kit PATH]          (fingerprints only)
The run is saved like one started on the page, and shows there.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from validation import runner
from validation.kit import ROLES, Kit, KitError
from validation.models import ValidationSettings


class Command(BaseCommand):
    help = 'Validate the Analysis page against the validation kit (raw data, OmniPC, calibration blocks).'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        run = sub.add_parser('run', help='Run the validation.')
        run.add_argument('--layers', default='', help='Comma-separated layer ids (default: all).')
        run.add_argument('--sweep', nargs='?', const=runner.default_sweep(), default=None,
                         help='Also decode every .nde file under this folder (default: the Reports folder).')
        add = sub.add_parser('add', help='Add a file to the kit (copied in, fingerprinted).')
        add.add_argument('file')
        add.add_argument('--roles', required=True, help=f"Comma-separated: {', '.join(ROLES)}")
        add.add_argument('--source', default='', help='Where it came from (e.g. "OmniPC 5.12 export, 2026-10-09").')
        add.add_argument('--notes', default='')
        sub.add_parser('check', help="Check the kit's fingerprints.")
        for p in (run, add, sub.choices['check']):
            p.add_argument('--kit', default=None, help='The kit folder (default: the one set on the Validation page).')

    def handle(self, action, kit=None, **options):
        path = kit or ValidationSettings.get().kit_path
        try:
            if action == 'add':
                entry = Kit(path).add(options['file'], [r.strip() for r in options['roles'].split(',') if r.strip()],
                                      options['source'], options['notes'])
                self.stdout.write(f"Added {entry['path']} ({entry['sha256'][:12]}…)")
            elif action == 'check':
                for c in Kit(path).verify():
                    self.stdout.write(f"{'ok  ' if c['ok'] else 'FAIL'} {c['path']} {c['reason']}")
            else:
                layers = [x.strip().upper() for x in options['layers'].split(',') if x.strip()]
                run = runner.create(layers, path, {'sweep': os.path.abspath(options['sweep'])} if options['sweep'] else {})
                self.stdout.write(f'Run {run.pk} at {run.version} on {path}')
                runner.execute(run)
                self._print(run)
        except KitError as e:
            raise CommandError(str(e)) from e

    def _print(self, run):
        r = run.results
        self.stdout.write(f"Kit: {r['kit'].get('message', r['kit'].get('status'))}")
        for c in r['kit'].get('files') or []:
            if not c['ok']:
                self.stdout.write(f"  FAIL {c['path']}: {c['reason']}")
        for layer in r['layers']:
            self.stdout.write(f"{layer['id']} {layer['title']}: {layer['status']} - {layer['message']}")
            for c in layer['checks']:
                if c['kind'] == 'check' and not c['passed']:
                    self.stdout.write(f"  FAIL {c['subject']}")
                    for i in c['items']:
                        if not i['ok']:
                            self.stdout.write(f"       {i['what']}: expected {i['expected']}, measured {i['measured']} ({i['rule']})")
        if r.get('error'):
            self.stdout.write(f"Error: {r['error']}")
        self.stdout.write(f'{run.status.upper()}: {run.passed} passed, {run.failed} failed')
