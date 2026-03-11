from django.forms import ModelForm
from .models import Report, Setup

class ReportForm(ModelForm):
    class Meta:
        model = Report
        fields = '__all__'

class SetupForm(ModelForm):
    class Meta:
        model = Setup
        fields = '__all__'