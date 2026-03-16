from django.forms import ModelForm, DateInput
from .models import Report, Setup
from datetime import date

class ReportForm(ModelForm):
    class Meta:
        model = Report
        fields = '__all__'
        widgets = {
            'report_date': DateInput(attrs={'type': 'date', 'value': date.today().isoformat()}),
            'test_date': DateInput(attrs={'type': 'date'}),
        }

class SetupForm(ModelForm):
    class Meta:
        model = Setup
        exclude = ['report']