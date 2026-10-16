"""
The validation layers, each answering one question against a source that doesn't share the Analysis
page's code. A layer's run(context) adds checks through context.emit(check); a check is one subject
(a file, an indication, a reflector...) with its items - expected (the independent source) against
measured (the Analysis page), the rule they're compared by, and whether they agree.
"""
from dataclasses import dataclass


@dataclass
class Layer:
    id: str
    title: str
    question: str          # what it proves
    against: str           # the independent source
    run: object = None     # run(context); None = not built yet

    @property
    def built(self):
        return self.run is not None


def item(what, expected, measured, ok, rule):
    """One comparison: what, the independent value, the app's value, whether they agree (None: shown,
    not compared - e.g. a reading the export has but the app can't check from it), and by what rule."""
    return {'what': what, 'expected': expected, 'measured': measured, 'ok': None if ok is None else bool(ok), 'rule': rule}


def check(title, subject, against, items, note='', kind='check', pictures=None):
    """
    One subject's comparisons. kind 'check' passes when every item agrees; 'info' is shown but not
    counted (e.g. a group the app says it can't show, listed so nothing is silently skipped).
    """
    return {'title': title, 'subject': subject, 'against': against, 'items': items, 'note': note, 'kind': kind,
            'pictures': pictures or [], 'passed': kind != 'check' or all(i['ok'] is not False for i in items)}


def _layers():
    from . import baseline, decoding, grading, readings, views
    return [
        Layer('L0', 'Decoding', 'Does the app read exactly what the scope recorded - every sample, axis, beam and gate?',
              'An independent HDF5 reader', decoding.run),
        Layer('L1', 'Readings', "Do the readings the app shows (A%, SA^, DA^, PA^, ViA^, thickness) match OmniPC's, digit for digit?",
              "OmniPC's indication exports", readings.run),
        Layer('L2', 'Sizing and detection', 'Does the app size indications like OmniPC, and find every indication a tech logged?',
              'Indications sized and logged in OmniPC'),
        Layer('L3', 'Physical accuracy', 'Are reflectors where they really are, as accurately as OmniPC places them?',
              'Calibration blocks with known reflectors'),
        Layer('L4', 'Views', 'Is every pixel the right colour, in the right place, for the data under it?',
              'The data under each pixel', views.run),
        Layer('L5', 'Grading and export', 'Are indications graded by the code exactly as written, and sent to reports unchanged?',
              "100-UT-020's acceptance criteria", grading.run),
        Layer('L6', 'Baseline', 'Does this version still give the results that were approved?',
              'The locked, approved results', baseline.run),
    ]


LAYERS = _layers()
BY_ID = {layer.id: layer for layer in LAYERS}
