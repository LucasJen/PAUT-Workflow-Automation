from django import forms
from reports.forms import StyledFormMixin
from .models import Scope, Probe, CalibrationBlock, SensitivityBlock, Encoder


class ScopeForm(StyledFormMixin, forms.ModelForm):
    fieldsets_spec = [
        ('Instrument', ['manufacturer', 'model', 'serial_number']),
        ('Software', ['software', 'software_version']),
        ('Calibration', ['calibration_date', 'calibration_due_date']),
    ]

    class Meta:
        model = Scope
        fields = '__all__'
        widgets = {
            'calibration_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'calibration_due_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }


class ProbeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Probe
        fields = '__all__'


class CalibrationBlockForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CalibrationBlock
        fields = '__all__'


class SensitivityBlockForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SensitivityBlock
        fields = '__all__'


class EncoderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Encoder
        fields = '__all__'
