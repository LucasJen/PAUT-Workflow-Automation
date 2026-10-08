from django import forms

from reports.forms import StyledFormMixin

from .models import AssistantSettings
from .providers import get_provider, provider_choices


class SettingsForm(StyledFormMixin, forms.ModelForm):
    """Preferences › Assistant. The key is write-only: left blank it keeps the saved one."""
    provider = forms.ChoiceField(choices=provider_choices, label='Provider')
    api_key = forms.CharField(
        label='API key', required=False, strip=True,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off', 'spellcheck': 'false'}),
        help_text='Create one at console.anthropic.com › API keys. Saved encrypted for your Windows user.')
    remove_key = forms.BooleanField(label='Remove the saved key', required=False)
    model = forms.ChoiceField(label='Model')

    class Meta:
        model = AssistantSettings
        fields = ['provider', 'model', 'monthly_cap']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings = self.instance
        if settings.has_key:
            self.fields['api_key'].widget.attrs['placeholder'] = '•••••••• saved; type a new key to replace it'
        else:
            del self.fields['remove_key']
        provider = get_provider(settings.provider)
        listed = [(m['id'], m['label']) for m in settings.model_list] or [(m.id, m.label) for m in provider.known_models()]
        if settings.model and settings.model not in dict(listed):
            listed.append((settings.model, settings.model))
        self.fields['model'].choices = listed
        self.fields['model'].help_text = ('Claude Haiku 4.5 is quick and the cheapest; Sonnet and Opus write more '
                                          'thorough summaries at 2× and 4× the price.')

    def save(self, commit=True):
        settings = super().save(commit=False)
        if self.cleaned_data.get('remove_key'):
            settings.api_key = ''
            settings.model_list = []
        elif self.cleaned_data.get('api_key'):
            settings.api_key = self.cleaned_data['api_key']
        if commit:
            settings.save()
        return settings
