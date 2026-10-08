from django import forms

from reports.forms import StyledFormMixin

from .models import AssistantSettings
from .providers import Usage, get_provider, provider_choices


class SettingsForm(StyledFormMixin, forms.ModelForm):
    """
    Preferences › Assistant, for the provider in use. Its key is write-only: left blank it keeps the
    saved one. Ollama takes an address instead of a key. Changing the provider reloads the page
    (settings.html) so the key, models and note shown are that provider's.
    """
    provider = forms.ChoiceField(choices=provider_choices, label='Provider')
    api_key = forms.CharField(label='API key', required=False, strip=True,
                              widget=forms.PasswordInput(attrs={'autocomplete': 'off', 'spellcheck': 'false'}))
    remove_key = forms.BooleanField(label='Remove the saved key', required=False)
    model = forms.ChoiceField(label='Model')

    class Meta:
        model = AssistantSettings
        fields = ['provider', 'model', 'ollama_url', 'input_price', 'output_price', 'monthly_cap']
        help_texts = {'input_price': 'Only used when the model\'s price isn\'t known (blank = shown as tokens).'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings = self.instance
        self.provider = provider = get_provider(settings.provider, settings)
        if provider.needs_key:
            del self.fields['ollama_url']
            self.fields['api_key'].help_text = f'{provider.key_help} Saved encrypted for your Windows user.'
            if settings.has_key:
                self.fields['api_key'].widget.attrs['placeholder'] = '•••••••• saved; type a new key to replace it'
            else:
                del self.fields['remove_key']
        else:
            del self.fields['api_key'], self.fields['remove_key']
            self.fields['ollama_url'].help_text = provider.key_help
        listed = ([(m['id'], m['label']) for m in settings.model_list]
                  or [(m.id, m.label) for m in provider.known_models()]
                  or [(provider.default_model, provider.default_model)])
        if settings.model and settings.model not in dict(listed):
            listed.append((settings.model, settings.model))
        self.fields['model'].choices = listed
        self.fields['model'].help_text = 'Use “Test & refresh models” to list every model your key (or Ollama) offers.'
        self.prices_known = provider.cost(settings.model, Usage()) is not None
        if self.prices_known:   # Claude's prices are built in; Ollama is free
            del self.fields['input_price'], self.fields['output_price']

    def save(self, commit=True):
        settings = super().save(commit=False)
        if self.cleaned_data.get('remove_key'):
            settings.api_key = ''
        elif self.cleaned_data.get('api_key'):
            settings.api_key = self.cleaned_data['api_key']
        if commit:
            settings.save()
        return settings

