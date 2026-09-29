from django.forms import (
    CheckboxInput, ChoiceField, ClearableFileInput, DateInput, HiddenInput, ModelForm, Select, Textarea,
    TextInput, inlineformset_factory,
)
from django.forms.renderers import TemplatesSetting
from .models import Report, Setup, ReportImage
from .report_types import DEFAULT_REPORT_TYPE, REPORT_SECTIONS, report_type_choices
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
    """
    Adds Bootstrap classes to every widget, and the `mono` class to MONO_FIELDS.

    Set `fieldsets_spec = [(title, [field names]), ...]` to group fields; templates
    loop over `form.fieldsets` to render each group.
    """
    fieldsets_spec = None

    def fieldsets(self):
        spec = self.fieldsets_spec or [(None, list(self.fields))]
        return [(title, [self[name] for name in names if name in self.fields]) for title, names in spec]

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
    report_type = ChoiceField(
        choices=report_type_choices, initial=DEFAULT_REPORT_TYPE, required=False, label='Report type',
    )

    def clean_report_type(self):
        return self.cleaned_data.get('report_type') or DEFAULT_REPORT_TYPE

    def sections(self):
        """Field sections for the editor: [(key, title, [bound fields])], special sections excluded."""
        return [
            (key, title, [self[name] for name in names if name in self.fields])
            for key, title, names in REPORT_SECTIONS if names
        ]

    class Meta:
        model = Report
        fields = '__all__'
        labels = {
            'document_filename': 'File name',
            'equipment_id': 'Equipment ID',
            'x_axis_reference': 'X-axis reference',
            'y_axis_reference': 'Y-axis reference',
            'ut_method': 'UT method',
        }
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
    fieldsets_spec = [
        ('UT equipment', ['manufacturer', 'scope_platform', 'scope_model', 'scope_serial',
                          'transducer_model', 'transducer_serial', 'probe_diameter']),
        ('Wedge', ['wedge_model', 'wedge_angle']),
        ('UT settings', ['foc_depth', 'wave_propagation', 'freq', 'elements', 'x_res', 'y_res',
                         'scan_length', 'scan_width', 'angle_step', 'angle_range', 'sound_velocity',
                         'gain', 'ref_gain', 'voltage']),
        ('Specimen', ['specimen_od', 'specimen_thickness']),
        ('Calibration', ['cal_material', 'material_temp', 'cal_block_type', 'cal_block_serial',
                         'surface_prep', 'tr_min', 'tr_max']),
    ]

    class Meta:
        model = Setup
        exclude = ['report', 'order']
        labels = {
            'foc_depth': 'Focal depth',
            'wave_propagation': 'Wave mode',
            'freq': 'Frequency',
            'x_res': 'X resolution',
            'y_res': 'Y resolution',
            'ref_gain': 'Reference gain',
            'specimen_od': 'Specimen OD',
            'cal_material': 'Calibration material',
            'material_temp': 'Material temperature',
            'cal_block_type': 'Cal block type',
            'cal_block_serial': 'Cal block serial',
            'surface_prep': 'Surface prep',
            'tr_min': 'TR min',
            'tr_max': 'TR max',
        }
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
