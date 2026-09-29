from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from equipment.forms import ScopeForm
from equipment.models import Probe, Scope
from reports.forms import SetupForm
from reports.models import Setup


class FieldsetTests(SimpleTestCase):
    def assert_covers_every_field_once(self, form):
        names = [bf.name for _, fields in form.fieldsets() for bf in fields]
        self.assertCountEqual(names, list(form.fields))

    def test_setup_fieldsets_cover_every_field(self):
        self.assert_covers_every_field_once(SetupForm())

    def test_scope_fieldsets_cover_every_field(self):
        self.assert_covers_every_field_once(ScopeForm())


class EditPageTests(TestCase):
    def test_setup_page_groups_fields_with_readable_labels(self):
        setup = Setup.objects.create()
        resp = self.client.get(reverse('edit-setup', args=[setup.pk]))
        self.assertContains(resp, '>UT settings</h2>')
        self.assertContains(resp, '>Focal depth:</label>')
        self.assertContains(resp, 'id="wave_propagation_options"')

    def test_save_precedes_delete_so_enter_saves(self):
        probe = Probe.objects.create()
        html = self.client.get(reverse('edit-probe', args=[probe.pk])).content.decode()
        self.assertLess(html.index('Save changes'), html.index('name="delete"'))
        self.assertIn('data-confirm="Delete this probe?', html)

    def test_save_shows_message_on_list(self):
        scope = Scope.objects.create()
        resp = self.client.post(reverse('edit-scope', args=[scope.pk]), {'model': 'X3'}, follow=True)
        self.assertContains(resp, 'Scope saved.')
        scope.refresh_from_db()
        self.assertEqual(scope.model, 'X3')

    def test_delete_from_edit_page(self):
        scope = Scope.objects.create()
        resp = self.client.post(reverse('edit-scope', args=[scope.pk]), {'delete': ''}, follow=True)
        self.assertContains(resp, 'Scope deleted.')
        self.assertFalse(Scope.objects.exists())
