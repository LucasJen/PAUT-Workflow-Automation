"""Matching an instrument file's probe and wedge to the catalogue, and the NDE import's use of it."""
import json
import os
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from equipment.compat import BEAMTOOL_SOURCE
from equipment.matching import base_name, match_probe, match_wedge, normalize
from equipment.models import ProbeModel, WedgeModel
from reports.forms import SetupForm
from reports.models import Setup
from reports.views.scan_plans import _setup_fill_values

SAMPLE_NDE = os.path.join(settings.BASE_DIR, 'outputs', '11v9 boot 12x12 trace obs.nde')

# The SA1-N60S 10L32 geometry from the Beamtool library, as an .nde file would give it
FILE_WEDGE = {'model': 'SA1-N60S 10L32', 'probe_series': 'A1', 'wedge_angle': 39.0, 'velocity': 2330.0,
              'primary_offset': -27.19, 'first_element_height': 5.15}
FILE_PROBE = {'model': '10L32-A1', 'series': 'A1', 'frequency': 10.0, 'elements': 32, 'pitch': 0.31}


def library_wedge(model, primary_offset, height, fit='10L32'):
    return WedgeModel.objects.create(model=model, manufacturer='Evident', probe_series='A1', probe_fit=fit,
                                     wedge_angle=39.0, velocity=2330.0, primary_offset=primary_offset,
                                     first_element_height=height, source=BEAMTOOL_SOURCE)


class MatchingTests(TestCase):
    def setUp(self):
        self.probe = ProbeModel.objects.get(model='10L32-A1')
        self.normal = library_wedge('SA1-N60S 10L32', -27.19, 5.15)
        self.reversed = library_wedge('SA1-N60S 10L32R', -26.27, 5.89)

    def test_names(self):
        self.assertEqual(normalize('SA1-N60S 10L32'), normalize('sa1_n60s-10l32'))
        self.assertEqual(base_name('SA1-N60S 10L32'), 'SA1-N60S')

    def test_probe_by_name_ignoring_punctuation(self):
        match = match_probe({**FILE_PROBE, 'model': '10L32 A1'})
        self.assertEqual((match.item, match.how), (self.probe, 'by name'))

    def test_probe_by_specs(self):
        match = match_probe({**FILE_PROBE, 'model': 'Custom 10MHz 32el'})
        self.assertEqual((match.item, match.how), (self.probe, 'by frequency, elements and pitch'))

    def test_unknown_probe(self):
        self.assertIsNone(match_probe({'model': '7.5L64-I4', 'series': 'I4', 'frequency': 7.5,
                                       'elements': 64, 'pitch': 1.0}).item)

    def test_wedge_by_name_without_differences(self):
        match = match_wedge(FILE_WEDGE, self.probe)
        self.assertEqual((match.item, match.how, match.differences), (self.normal, 'by name', []))

    def test_wedge_variant_picked_by_geometry(self):
        """OmniScan calls it 'SA1-N60S'; its geometry says it is the reversed (R) mounting."""
        match = match_wedge({**FILE_WEDGE, 'model': 'SA1-N60S', 'primary_offset': -26.3, 'first_element_height': 5.9},
                            self.probe)
        self.assertEqual(match.item, self.reversed)
        self.assertEqual(match.how, 'closest geometry among SA1-N60S variants')

    def test_wedge_by_geometry_alone(self):
        match = match_wedge({**FILE_WEDGE, 'model': 'My modified wedge'}, self.probe)
        self.assertEqual((match.item, match.how), (self.normal, 'by geometry'))

    def test_differences_are_listed(self):
        match = match_wedge({**FILE_WEDGE, 'primary_offset': -26.0, 'velocity': 2337.0}, self.probe)
        self.assertEqual(match.item, self.normal)
        self.assertEqual(match.differences, [('primary offset', '-27.19 mm', '-26 mm')])

    def test_no_wedge_match(self):
        self.assertIsNone(match_wedge({'model': 'HydroFORM', 'wedge_angle': 0.0, 'velocity': 1480.0,
                                       'primary_offset': -71.0, 'first_element_height': 13.0}, self.probe).item)


GROUP = {
    'id': 0, 'label': 'GR-1 · Sectorial',
    'values': {'imperial': {'transducer_model': '10L32-A1'}, 'metric': {'transducer_model': '10L32-A1'}},
    'hardware': {
        'probe': {'model': '10L32-A1', 'serie': 'A1', 'phasedArrayLinear': {
            'centralFrequency': 10e6, 'primaryAxis': {'elementQuantity': 32, 'elementLength': 0.00031},
            'secondaryAxis': {'elementLength': 0.007}}},
        'wedge': {'model': 'SA1-N60S 10L32', 'serie': 'SA1', 'angleBeamWedge': {
            'longitudinalVelocity': 2330.0,
            'mountingLocations': [{'id': 0, 'wedgeAngle': 39.0, 'primaryOffset': -0.02719, 'tertiaryOffset': 0.00515}]}},
        'mounting_id': 0, 'first_element': 1, 'aperture': 27,
    },
}


@mock.patch('reports.views.nde.read_nde', return_value=({}, {}))
@mock.patch('reports.views.nde.extract_groups')
class NdeImportMatchTests(TestCase):
    def upload(self):
        return self.client.post(reverse('nde-upload'), {'nde_file': SimpleUploadedFile('weld.nde', b'x')})

    def test_matched_probe_and_wedge_fill_the_setup(self, extract, _read):
        wedge = library_wedge('SA1-N60S 10L32', -27.19, 5.15)
        extract.return_value = [json.loads(json.dumps(GROUP))]
        resp = self.upload()
        group = resp.context['nde_groups'][0]
        probe = ProbeModel.objects.get(model='10L32-A1')
        self.assertEqual(group['values']['imperial']['catalogue_probe'], probe.pk)
        self.assertEqual(group['values']['metric']['catalogue_wedge'], wedge.pk)
        self.assertEqual((group['values']['imperial']['first_element'], group['values']['imperial']['aperture_elements']),
                         (1, 27))
        self.assertEqual(group['catalogue']['wedge']['how'], 'by name')
        self.assertNotIn('hardware', group)
        self.assertContains(resp, 'id="catalogue-match"')

    def test_unmatched_wedge_offers_its_file_values(self, extract, _read):
        group = json.loads(json.dumps(GROUP))
        group['hardware']['wedge']['model'] = 'ABC-Custom wedge'
        extract.return_value = [group]
        group = self.upload().context['nde_groups'][0]
        self.assertEqual(group['values']['imperial']['catalogue_wedge'], '')
        wedge = group['catalogue']['wedge']
        self.assertNotIn('pk', wedge)
        self.assertEqual(wedge['file_fields']['primary_offset'], -27.19)


class AddFromFileTests(TestCase):
    def post(self, body):
        return self.client.post(reverse('catalogue-add-from-file'), json.dumps(body), content_type='application/json')

    def test_adds_a_wedge_with_its_source(self):
        resp = self.post({'kind': 'wedge', 'file': 'weld.nde', 'fields': {**FILE_WEDGE, 'model': 'SA1-N60S custom',
                                                                         'secret': 'ignored'}})
        wedge = WedgeModel.objects.get(model='SA1-N60S custom')
        self.assertEqual(resp.json(), {'pk': wedge.pk, 'name': 'SA1-N60S custom'})
        self.assertEqual(wedge.source, 'OmniScan file weld.nde')
        self.assertTrue(wedge.has_geometry)

    def test_rejects_bad_requests(self):
        self.assertEqual(self.post({'kind': 'scope', 'fields': {}}).status_code, 400)
        self.assertEqual(self.post({'kind': 'probe', 'fields': {}}).status_code, 400)
        self.assertEqual(self.client.get(reverse('catalogue-add-from-file')).status_code, 405)


class SetupLinkTests(TestCase):
    def test_setup_saves_links_and_scan_plan_fill_carries_them(self):
        probe = ProbeModel.objects.get(model='10L32-A1')
        wedge = library_wedge('SA1-N60S 10L32', -27.19, 5.15)
        form = SetupForm({'manufacturer': 'Evident', 'catalogue_probe': probe.pk, 'catalogue_wedge': wedge.pk,
                          'first_element': 1, 'aperture_elements': 27, 'specimen_thickness': '0.280'})
        self.assertTrue(form.is_valid(), form.errors)
        setup = form.save()
        fill = _setup_fill_values()[setup.pk]['fields']
        self.assertEqual((fill['probe_model'], fill['wedge_model'], fill['first_element'], fill['aperture_elements']),
                         (probe.pk, wedge.pk, 1, 27))

    def test_setup_wedge_list_follows_its_probe(self):
        probe = ProbeModel.objects.get(model='10L32-A1')
        library_wedge('SA1-N60S 10L32', -27.19, 5.15)
        library_wedge('SA1-N60S 5L16', -27.2, 5.1, fit='5L16')
        setup = Setup.objects.create(catalogue_probe=probe)
        choices = [label for _, label in SetupForm(instance=setup).fields['catalogue_wedge'].widget.choices]
        self.assertIn('SA1-N60S 10L32', choices)
        self.assertNotIn('SA1-N60S 5L16', choices)
