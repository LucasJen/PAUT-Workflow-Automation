"""
The validation kit: one folder holding everything a validation run checks against - the .nde files,
OmniPC's exports, calibration block definitions and baselines - with a manifest, kit.json, that lists
each file, its SHA-256 fingerprint, what it's used for (roles) and where it came from. A run checks
every fingerprint first and won't use a file that doesn't match, so the evidence can't change
unnoticed. The kit is plain files: copy the folder to another PC to show the same run there.

kit.json:
    {"name": "...", "files": [{"path": "nde/x.nde", "sha256": "...", "size": 123, "roles": ["decoding"],
                                "source": "Scanned 2026-10-09, OmniPC 5.x", "notes": "", "added": "2026-10-15T..."}]}
"""
import datetime
import hashlib
import json
import os
import shutil

MANIFEST = 'kit.json'
DEFAULT_PATH = os.path.expanduser('~/Desktop/Reports/Validation kit')

# What a file is used for: the layers that use it
ROLES = {
    'decoding': 'Raw data decoding (L0)',
    'readings': 'OmniPC readings (L1)',
    'fields': 'OmniPC C-scan export (L1)',
    'sizing': 'OmniPC sizing (L2)',
    'detection': 'Fully evaluated in OmniPC (L2)',
    'block': 'Calibration block (L3)',
    'views': 'Views and pictures (L4)',
    'baseline': 'Locked baseline (L6)',
}
# Where an added file goes in the kit, by its type
FOLDERS = {'.nde': 'nde', '.json': 'points', '.csv': 'omnipc', '.zip': 'omnipc', '.txt': 'omnipc',
           '.png': 'pictures', '.jpg': 'pictures', '.jpeg': 'pictures'}


class KitError(Exception):
    """The kit can't be used as asked (missing, a bad manifest, a file that can't be added)."""


def sha256(path, progress=None):
    """The file's SHA-256 (hex), read in 8 MB pieces; progress(bytes done, total) after each."""
    digest, done = hashlib.sha256(), 0
    total = os.path.getsize(path)
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            digest.update(block)
            done += len(block)
            if progress:
                progress(done, total)
    return digest.hexdigest()


class Kit:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.manifest = {'name': os.path.basename(self.root), 'files': []}
        self.exists = os.path.isdir(self.root)
        path = os.path.join(self.root, MANIFEST)
        if os.path.isfile(path):
            try:
                with open(path, encoding='utf-8') as f:
                    self.manifest = json.load(f)
            except (OSError, ValueError) as e:
                raise KitError(f"The kit's manifest ({MANIFEST}) can't be read: {e}") from e
            self.manifest.setdefault('files', [])

    @property
    def files(self):
        return self.manifest['files']

    def full_path(self, entry):
        return os.path.join(self.root, entry['path'])

    def with_role(self, role):
        return [e for e in self.files if role in (e.get('roles') or [])]

    def nde_files(self):
        return [e for e in self.files if e['path'].lower().endswith('.nde')]

    def manifest_sha(self):
        """A fingerprint of the manifest itself: what was in the kit for a run."""
        return hashlib.sha256(json.dumps(self.manifest, sort_keys=True).encode()).hexdigest()

    def save(self):
        os.makedirs(self.root, exist_ok=True)
        path = os.path.join(self.root, MANIFEST)
        with open(path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, indent=2)
        os.replace(path + '.tmp', path)
        self.exists = True

    def verify(self, progress=None):
        """
        Each listed file checked against its fingerprint: [{path, ok, reason}], reason '' when it matches.
        progress(message, fraction) as it goes (the big .nde files take a few seconds each).
        """
        out, total = [], sum(e.get('size') or 0 for e in self.files) or 1
        done = 0
        for entry in self.files:
            path = self.full_path(entry)
            if not os.path.isfile(path):
                out.append({'path': entry['path'], 'ok': False, 'reason': 'missing from the kit'})
                continue
            base = done
            report = (lambda d, t, b=base, name=entry['path']: progress(f'Fingerprinting {name}', (b + d) / total)) if progress else None
            actual = sha256(path, report)
            done += entry.get('size') or 0
            if actual != entry.get('sha256'):
                out.append({'path': entry['path'], 'ok': False,
                            'reason': f"changed since it was added (SHA-256 {actual[:12]}…, listed {str(entry.get('sha256'))[:12]}…)"})
            else:
                out.append({'path': entry['path'], 'ok': True, 'reason': ''})
        return out

    def add(self, source, roles, origin='', notes='', copy=True):
        """
        Adds a file to the kit (copied into its folder by type, or listed in place when it's already
        inside the kit) with its fingerprint; a file of the same kit path is replaced. Returns the entry.
        """
        source = os.path.abspath(source)
        if not os.path.isfile(source):
            raise KitError(f'No such file: {source}')
        unknown = [r for r in roles if r not in ROLES]
        if unknown:
            raise KitError(f"Unknown role{'s' if len(unknown) > 1 else ''}: {', '.join(unknown)}")
        os.makedirs(self.root, exist_ok=True)
        if os.path.commonpath([source, self.root]) == self.root:
            target = source
        else:
            folder = FOLDERS.get(os.path.splitext(source)[1].lower(), 'other')
            target = os.path.join(self.root, folder, os.path.basename(source))
            if copy:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
        rel = os.path.relpath(target, self.root).replace(os.sep, '/')
        entry = {'path': rel, 'sha256': sha256(target), 'size': os.path.getsize(target), 'roles': list(roles),
                 'source': origin, 'notes': notes, 'added': datetime.datetime.now().isoformat(timespec='seconds')}
        self.manifest['files'] = [e for e in self.files if e['path'] != rel] + [entry]
        self.save()
        return entry
