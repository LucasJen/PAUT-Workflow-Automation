from django.forms import (
    CheckboxInput, ChoiceField, ClearableFileInput, DateInput, HiddenInput, ModelForm, Select, Textarea,
    TextInput, inlineformset_factory,
)
from django.forms.renderers import TemplatesSetting
from .models import Report, ReportImage, ReportPerson, Setup
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
    'beam_gain', 'active_elements', 'element_aperture', 'element_step', 'pcs', 'digitizing_frequency',
    'pulse_width', 'band_pass_filter', 'acquisition_date',
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
        return [section for section in self.all_sections() if section[2]]

    def all_sections(self):
        """Every editor section in order; special sections (setups, results, ...) have fields=None."""
        return [
            (key, title, [self[name] for name in names if name in self.fields] if names else None)
            for key, title, names in REPORT_SECTIONS
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
            'test_date': 'Test start date',
            'test_end_date': 'Test end date',
        }
        widgets = {
            'document_title': Textarea(attrs={'rows': 1, 'style': 'min-height: 0; resize: vertical;'}),
            'report_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'test_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'test_end_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }
        help_texts = {'test_end_date': 'Leave blank for a single-day test.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default new reports to today (evaluated per request, not once at server start)
        if self.instance.pk is None:
            self.initial.setdefault('report_date', date.today())


class SetupForm(StyledFormMixin, ModelForm):
    fieldsets_spec = [
        ('Technique', ['title', 'procedure']),
        ('UT equipment', ['manufacturer', 'scope_platform', 'scope_model', 'scope_serial',
                          'transducer_model', 'transducer_serial', 'probe_diameter']),
        ('Wedge', ['wedge_model', 'wedge_angle']),
        ('UT settings', ['foc_depth', 'wave_propagation', 'freq', 'elements', 'x_res', 'y_res',
                         'scan_length', 'scan_width', 'angle_step', 'angle_range', 'sound_velocity',
                         'gain', 'beam_gain', 'ref_gain', 'voltage']),
        ('Acquisition', ['beam_formation', 'active_elements', 'element_aperture', 'element_step', 'pcs',
                         'scan_pattern', 'encoder_resolution', 'digitizing_frequency', 'pulse_width',
                         'band_pass_filter', 'calibrations', 'gates']),
        ('Specimen', ['specimen_od', 'specimen_thickness', 'specimen_dimensions']),
        ('Calibration', ['cal_material', 'material_temp', 'cal_block_type', 'cal_block_serial',
                         'surface_prep', 'tr_min', 'tr_max']),
        ('Source', ['source_file', 'acquisition_date']),
    ]

    class Meta:
        model = Setup
        exclude = ['report', 'order']
        labels = {
            'title': 'Technique title',
            'procedure': 'Procedure',
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
            'gain': 'Gain (group, dB)',
            'beam_gain': 'Beam gain (dB)',
            'beam_formation': 'Beam formation',
            'active_elements': 'Active elements',
            'element_aperture': 'Element aperture',
            'element_step': 'Element step',
            'pcs': 'PCS (TOFD)',
            'encoder_resolution': 'Encoder resolution',
            'digitizing_frequency': 'Digitizing frequency (MHz)',
            'pulse_width': 'Pulse width (ns)',
            'band_pass_filter': 'Band-pass filter (MHz)',
            'calibrations': 'Calibrations performed',
            'specimen_dimensions': 'Specimen dimensions',
            'source_file': 'Source data file',
            'acquisition_date': 'Acquisition date',
        }
        widgets = {
            'wave_propagation': TextInput(attrs={'list': 'wave_propagation_options'}),
            'gates': Textarea(attrs={'rows': 2}),
            'title': TextInput(attrs={'placeholder': 'e.g. HydroFORM, Angle Beam, TFM'}),
            'procedure': TextInput(attrs={'placeholder': 'e.g. 100-UT-031 Rev. 1'}),
        }
        help_texts = {'title': 'Heads this setup\'s "Equipment Details" section in the report.'}


class DrawingForm(StyledFormMixin, ModelForm):
    """Equipment / isometric drawings, shown under the report's Drawing heading."""

    class Meta:
        model = ReportImage
        fields = ['image', 'caption']  # order comes from position on the page
        labels = {'caption': 'Drawing title', 'image': 'Drawing'}
        widgets = {
            'image': ClearableFileInput(attrs={'accept': 'image/*'}),
            'caption': TextInput(attrs={'placeholder': 'e.g. FILE DRAWING, NOZZLE LAYOUT'}),
        }


class ScanImageForm(StyledFormMixin, ModelForm):
    """Photo-summary data snips; each is tied to a results-table row by Scan ID."""

    class Meta:
        model = ReportImage
        fields = ['image', 'scan_id', 'caption']  # order comes from position on the page
        labels = {'image': 'Scan image', 'scan_id': 'Scan ID', 'caption': 'Label (if not in results table)'}
        widgets = {
            'image': ClearableFileInput(attrs={'accept': 'image/*'}),
            'scan_id': Select(attrs={'class': 'scan-id-select'}),
        }

    def __init__(self, *args, scan_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        # Options are the results table's Scan IDs; the editor's JS keeps them in step as the
        # table is edited. Keep the saved value even if its row has since been renamed.
        current = self.initial.get('scan_id') or (self.data.get(self.add_prefix('scan_id')) if self.is_bound else '')
        ids = list(dict.fromkeys(scan_ids))
        choices = [('', '— Select scan —')] + [(i, i) for i in ids]
        if current and current not in ids:
            choices.append((current, f'{current} (not in results table)'))
        self.fields['scan_id'].widget.choices = choices


SetupFormSet = inlineformset_factory(
    Report, Setup, form=SetupForm,
    extra=1, can_delete=True
)

DrawingFormSet = inlineformset_factory(
    Report, ReportImage, form=DrawingForm,
    extra=0, can_delete=True,
)



class ReportPersonForm(StyledFormMixin, ModelForm):
    class Meta:
        model = ReportPerson
        fields = ['name', 'certification', 'prepared', 'examined', 'reviewed']
        widgets = {
            'name': TextInput(attrs={'list': 'known-people', 'autocomplete': 'off'}),
            'certification': TextInput(attrs={'placeholder': 'e.g. Ultrasonic Level II'}),
        }


PersonFormSet = inlineformset_factory(
    Report, ReportPerson, form=ReportPersonForm,
    extra=0, can_delete=True,
)

ImageFormSet = inlineformset_factory(
    Report, ReportImage, form=ScanImageForm,
    extra=0, can_delete=True,
)


def drawing_formset(*args, instance=None, **kwargs):
    return DrawingFormSet(*args, instance=instance, prefix='drawings',
                          queryset=ReportImage.objects.filter(kind=ReportImage.DRAWING), **kwargs)


def scan_image_formset(*args, instance=None, scan_ids=(), **kwargs):
    return ImageFormSet(*args, instance=instance, prefix='images',
                        queryset=ReportImage.objects.filter(kind=ReportImage.SCAN),
                        form_kwargs={'scan_ids': scan_ids}, **kwargs)
