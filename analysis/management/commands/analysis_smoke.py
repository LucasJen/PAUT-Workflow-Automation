"""
Opens every .nde file under a folder (default: the user's Reports folder) with the Analysis data
engine, reads one frame of each group, and lists what was found: the layouts read, unsupported
groups (e.g. TFM) and any files that failed. Run by hand; not part of the test suite.
"""
import collections
import os
import time

from django.core.management.base import BaseCommand

from analysis.services.nde_data import UNSUPPORTED, NdeDataError, open_file, read_frame


class Command(BaseCommand):
    help = 'Open every .nde file under a folder with the Analysis data engine and report the results.'

    def add_arguments(self, parser):
        parser.add_argument('folder', nargs='?', default=os.path.expanduser('~/Desktop/Reports'))
        parser.add_argument('--limit', type=int, default=0, help='Stop after this many files.')

    def handle(self, folder, limit, **options):
        layouts, unsupported, failures = collections.Counter(), collections.Counter(), []
        count, started = 0, time.time()
        for root, _, files in os.walk(folder):
            for name in sorted(files):
                if not name.lower().endswith('.nde'):
                    continue
                path = os.path.join(root, name)
                count += 1
                try:
                    info = open_file(path)
                    for group in info.groups:
                        if group.layout == UNSUPPORTED:
                            unsupported[group.reason] += 1
                            continue
                        frame, _ = read_frame(path, group, group.shape[0] // 2)
                        layouts[(group.layout, group.formation or '?')] += 1
                except (NdeDataError, Exception) as e:   # report every kind of failure, keep going
                    failures.append((path, f'{type(e).__name__}: {e}'))
                if limit and count >= limit:
                    break
            if limit and count >= limit:
                break
        self.stdout.write(f'{count} files in {time.time() - started:.1f} s')
        for key, n in sorted((k, v) for k, v in layouts.items() if len(k) == 2):
            self.stdout.write(f'  read     {n:4d} group(s): {key[0]} / {key[1]}')
        for reason, n in unsupported.items():
            self.stdout.write(f'  skipped  {n:4d} group(s): {reason}')
        for path, error in failures:
            self.stdout.write(self.style.ERROR(f'  FAILED   {path}: {error}'))
        if not failures:
            self.stdout.write(self.style.SUCCESS('No failures.'))
