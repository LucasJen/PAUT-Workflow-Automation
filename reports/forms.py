from django.forms import (
    CheckboxInput, ChoiceField, ClearableFileInput, DateInput, HiddenInput, ModelForm, NumberInput, Select, Textarea,
    TextInput, inlineformset_factory,
)
from django.forms.renderers import TemplatesSetting
from django.urls import reverse_lazy
from django.utils.choices import CallableChoiceIterator
from equipment.compat import BEAMTOOL_SOURCE, wedge_fits_probe, wedges_for_probe
from equipment.models import ProbeModel

from .models import Report, ReportImage, ReportPerson, ScanPlan, Setup, TextSnippet
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
    'thickness', 'bevel_angle', 'root_gap', 'root_face', 'cap_width', 'index_offset', 'exit_point',
    'wedge_angle', 'angle_start', 'angle_stop', 'angle_step',
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
            'ut_method': 'UT method (used only when no setup has a Technique title)',
            'asset_description': 'Asset description',
            'equipment_overview': 'Access & surface condition',
            'discussion': 'Discussion',
            'test_date': 'Test start date',
            'test_end_date': 'Test end date',
            'procedure_rev': 'Procedure rev.',
            'item_description': 'Item description',
            'exam_code': 'Exam code / specification',
            'cal_time_initial': 'Initial calibration time',
            'cal_time_check1': 'Calibration check time',
            'cal_time_check2': 'Second calibration check time',
            'cal_time_out': 'Calibration out time',
            'scan_plan': 'Scan plan',
        }
        widgets = {
            'document_title': Textarea(attrs={'rows': 1, 'style': 'min-height: 0; resize: vertical;'}),
            'report_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'test_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'test_end_date': DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'notes': Textarea(attrs={'rows': 3}),
        }
        help_texts = {
            'cal_time_initial': '24-hour time, e.g. 0700. Amp, sweep and probe position print as Accept.',
            'notes': 'Notes box at the bottom of the weld form.',
            'scan_plan': 'Printed on the last page. Create and edit scan plans under Scan plans.',
            'test_end_date': 'Leave blank for a single-day test.',
            'asset_description': 'Opening paragraph of the Introduction: what the asset is, material, design and service conditions.',
            'discussion': 'Leave blank to use the standard Discussion from the Text library.',
            'ut_method': 'One technique per line, e.g. "ENCODED HydroFORM 0-degree PAUT – description". '
                         'Only used when no setup has a Technique title; setting Technique titles uses the '
                         'Text library instead.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default new reports to today (evaluated per request, not once at server start)
        if self.instance.pk is None:
            self.initial.setdefault('report_date', date.today())


def catalogue_choices(form, probe_name, wedge_name):
    """
    Probe / wedge catalogue selects on a form: the wedge list shows only wedges that fit the chosen
    probe (the Beamtool library has many); static/reports/js/catalogue_select.js refreshes it when the
    probe changes and adds type-to-filter boxes. Validation still accepts any wedge.
    """
    probe_field, wedge_field = form.fields[probe_name], form.fields[wedge_name]
    probe_field.widget.attrs['data-catalogue'] = 'probe'
    wedge_field.widget.attrs.update({'data-catalogue': 'wedge', 'data-wedges-url': reverse_lazy('scan-plan-wedges')})

    def chosen(name):
        value = form.data.get(form.add_prefix(name)) if form.is_bound else getattr(form.instance, f'{name}_id', None)
        return value if value not in (None, '') else None

    probe_pk, wedge_pk = chosen(probe_name), chosen(wedge_name)
    if not (probe_pk and str(probe_pk).isdigit()):
        probe_pk = None
        wedge_field.help_text = 'Pick a probe first to list the library wedges made for it.'

    def wedge_choices():
        # Worked out when the select is drawn, so building the form doesn't query the catalogue
        probe = ProbeModel.objects.filter(pk=probe_pk).first() if probe_pk else None
        wedges = list(wedge_field.queryset)
        if probe is not None:
            shown = wedges_for_probe(probe, wedges)
        else:
            shown = [w for w in wedges if w.source != BEAMTOOL_SOURCE]
        shown += [w for w in wedges if str(w.pk) == str(wedge_pk) and w not in shown]
        return [('', wedge_field.empty_label)] + [(w.pk, str(w)) for w in shown]

    wedge_field.widget.choices = CallableChoiceIterator(wedge_choices)


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
        ('Catalogue probe and wedge (for scan plans)', ['catalogue_probe', 'catalogue_wedge', 'first_element',
                                                        'aperture_elements']),
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
        help_texts = {'title': 'Heads this setup\'s "Equipment Details" section. The Introduction\'s technique '
                               'bullet uses the Text library description with this name.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        catalogue_choices(self, 'catalogue_probe', 'catalogue_wedge')


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


class TextSnippetForm(StyledFormMixin, ModelForm):
    class Meta:
        model = TextSnippet
        fields = ['kind', 'name', 'title', 'body']
        labels = {'name': 'Name', 'title': 'Bold lead', 'body': 'Text'}
        widgets = {'body': Textarea(attrs={'rows': 8})}


SCAN_PLAN_NUMBERS = (
    'thickness', 'bevel_angle', 'root_gap', 'root_face', 'cap_width', 'index_offset', 'exit_point',
    'wedge_angle', 'angle_start', 'angle_stop', 'angle_step', 'shear_velocity',
)


class ScanPlanForm(StyledFormMixin, ModelForm):
    fieldsets_spec = [
        ('Scan plan', ['name', 'sensitivity_block', 'pipe_size', 'sides', 'legs']),
        ('Weld (inches, degrees)', ['thickness', 'bevel_angle', 'root_gap', 'root_face', 'cap_width', 'shear_velocity']),
        ('Probe and wedge', ['probe_model', 'wedge_model', 'first_element', 'aperture_elements']),
        ('Position and beams', ['index_offset', 'exit_point', 'wedge_angle', 'angle_start', 'angle_stop', 'angle_step']),
        (None, ['notes']),
    ]
    LENGTHS = ('thickness', 'root_gap', 'root_face', 'cap_width', 'index_offset', 'exit_point')
    ANGLES = ('bevel_angle', 'wedge_angle', 'angle_start', 'angle_stop')

    class Meta:
        model = ScanPlan
        exclude = ['updated_at']
        labels = {
            'pipe_size': 'Pipe size',
            'bevel_angle': 'Bevel angle (°)',
            'root_gap': 'Root gap',
            'root_face': 'Root face (land)',
            'cap_width': 'Cap width',
            'index_offset': 'Index offset',
            'exit_point': 'Exit point',
            'wedge_angle': 'Wedge angle (°)',
            'angle_start': 'Start angle (°)',
            'angle_stop': 'Stop angle (°)',
            'angle_step': 'Angle step (°)',
            'legs': 'Beam legs',
            'notes': 'Notes (printed under the scan plan)',
            'sensitivity_block': 'Sensitivity block (pipe size)',
            'shear_velocity': 'Shear velocity (in/µs)',
            'aperture_elements': 'Aperture (elements)',
        }
        help_texts = {
            'exit_point': 'Used only when the wedge has no geometry; otherwise each beam’s exit point is calculated.',
            'wedge_angle': 'Filled from the wedge; used for the sketched wedge.',
        }
        widgets = {
            'notes': Textarea(attrs={'rows': 2}),
            **{name: NumberInput(attrs={'step': 'any'}) for name in SCAN_PLAN_NUMBERS},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        catalogue_choices(self, 'probe_model', 'wedge_model')

    def clean(self):
        data = super().clean()
        if data.get('thickness') is not None and data['thickness'] <= 0:
            self.add_error('thickness', 'Enter a thickness above 0.')
        for name in self.LENGTHS:
            if data.get(name) is not None and data[name] < 0:
                self.add_error(name, 'Cannot be negative.')
        for name in self.ANGLES:
            if data.get(name) is not None and not 0 <= data[name] < 90:
                self.add_error(name, 'Enter an angle from 0 to 89°.')
        if data.get('angle_step') is not None and data['angle_step'] <= 0:
            self.add_error('angle_step', 'Enter a step above 0.')
        probe, wedge = data.get('probe_model'), data.get('wedge_model')
        if probe and wedge and not wedge_fits_probe(wedge, probe):
            fits = f'{wedge.probe_series} probes' if wedge.probe_series else 'a different probe'
            self.add_error('wedge_model', f'{wedge} fits {fits}, not {probe}.')
        if (data.get('thickness') and data.get('root_face') is not None and data['root_face'] > data['thickness']):
            self.add_error('root_face', 'The root face cannot be thicker than the wall.')
        return data
