from django.forms import ModelForm, DateInput, Textarea, TextInput
from .models import Report, Setup
from datetime import date

class ReportForm(ModelForm):
    class Meta:
        model = Report
        fields = '__all__'
        widgets = {
            'document_title': Textarea(attrs={'rows': 1, 'style': 'min-height: 0; resize: vertical;'}),
            'report_date': DateInput(attrs={'type': 'date', 'value': date.today().isoformat()}),
            'test_date': DateInput(attrs={'type': 'date'}),
        }

class SetupForm(ModelForm):
    class Meta:
        model = Setup
        exclude = ['report']
        widgets = {
            'wave_propagation': TextInput(attrs={'list':'wave_propagation_options'})
        }
    