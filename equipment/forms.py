from django import forms
from .models import Scope, Probe, CalibrationBlock, SensitivityBlock, Encoder


class ScopeForm(forms.ModelForm):
    class Meta:
        model = Scope
        fields = '__all__'


class ProbeForm(forms.ModelForm):
    class Meta:
        model = Probe
        fields = '__all__'


class CalibrationBlockForm(forms.ModelForm):
    class Meta:
        model = CalibrationBlock
        fields = '__all__'


class SensitivityBlockForm(forms.ModelForm):
    class Meta:
        model = SensitivityBlock
        fields = '__all__'


class EncoderForm(forms.ModelForm):
    class Meta:
        model = Encoder
        fields = '__all__'
