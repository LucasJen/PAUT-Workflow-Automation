from django.forms import (
    CheckboxInput, ClearableFileInput, DateInput, HiddenInput, ModelForm, Select, Textarea, TextInput,
    inlineformset_factory,
)
from django.forms.renderers import TemplatesSetting
from .models import Report, Setup, ReportImage
from datetime import date


class AppFormRenderer(TemplatesSetting):
    """Renders {{ form.field.as_field_group }} with the app's label-above field layout."""
    field_template_name = 'reports/components/field.html'


# Fields shown in the monospace face: serials, IDs and numeric values
MONO_FIELDS = {
    'work_order', 'project_number', 'equipment_id',
    'scope_serial', 'transducer_serial', 'cal_block_serial', 'serial_number', 'software_version',
    'probe_diameter', 'wedge_angle', 'foc_depth', 'freq', 'elements', 'x_res', 'y_res',
    'scan_length', 'scan_width', 'angle_step', 'angle_range', 'sound_velocity', 'gain',
    'ref_gain', 'voltage', 'specimen_od', 'specimen_thickness', 'material_temp', 'tr_min', 'tr_max',
    'frequency', 'diameter', 'step_count',
}


class StyledFormMixin:
    """Adds Bootstrap classes to every widget, and the `mono` class to MONO_FIELDS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, HiddenInput):
                continue
            if isinstance(widget, CheckboxInput):
                css = 'form-check-input'
            elif isinstance(widget, Select):
                css = 'form-select'
            else:
                css = 'form-control'
            if name in MONO_FIELDS:
                css += ' mono'
            if isinstance(widget, Textarea) and widget.attrs.get('rows') == '10':
                widget.attrs['rows'] = 4  # Django's default of 10 rows is too tall for this layout
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css}".strip()


class ReportForm(StyledFormMixin, ModelForm):
    class Meta:
        model = Report
        fields = '__all__'
        widgets = {
            'document_title': Textarea(attrs={'rows': 1, 'style': 'min-height: 0; resize: vertical;'}),
            'report_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'test_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default new reports to today (evaluated per request, not once at server start)
        if self.instance.pk is None:
            self.initial.setdefault('report_date', date.today())


class SetupForm(StyledFormMixin, ModelForm):
    class Meta:
        model = Setup
        exclude = ['report', 'order']
        widgets = {
            'wave_propagation': TextInput(attrs={'list': 'wave_propagation_options'})
        }


class ReportImageForm(StyledFormMixin, ModelForm):
    class Meta:
        model = ReportImage
        fields = ['image', 'caption', 'order']
        widgets = {'order': HiddenInput, 'image': ClearableFileInput(attrs={'accept': 'image/*'})}


SetupFormSet = inlineformset_factory(
    Report, Setup, form=SetupForm,
    extra=1, can_delete=True
)

ImageFormSet = inlineformset_factory(
    Report, ReportImage, form=ReportImageForm,
    extra=1, can_delete=True,
)
