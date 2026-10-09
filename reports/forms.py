from django.forms import (
    CheckboxInput, ChoiceField, ClearableFileInput, DateInput, HiddenInput, ModelForm, NumberInput, RadioSelect, Select,
    Textarea, TextInput, ValidationError, inlineformset_factory,
)
from django.forms.renderers import TemplatesSetting
from django.urls import reverse_lazy
from django.utils.choices import CallableChoiceIterator
from equipment.compat import BEAMTOOL_SOURCE, wedge_fits_probe, wedges_for_probe
from equipment.models import ProbeModel

from . import fill_marks, weld_form
from .models import (
    ClientCode, Report, ReportGroup, ReportImage, ReportPerson, ReportProbe, ScanPlan, Setup, TextSnippet, WorkingFolder,
)
from .report_types import DEFAULT_REPORT_TYPE, REPORT_SECTIONS, get_report_type, report_type_choices
from .services.scan_plan import reflectors as scan_plan_reflectors
from .services.scan_plan.geometry import first_number
from datetime import date
from pathlib import Path
import json
import os


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

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('test_date'), cleaned.get('test_end_date')
        # Only where the end date is shown: a type that hides it keeps the value, unseen
        shown = 'test_end_date' not in get_report_type(cleaned.get('report_type')).hidden_fields
        if start and end and end < start and shown:
            self.add_error('test_end_date', 'The test end date is before the start date.')
        return cleaned

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
        # Set by Guided Creation and the job folder bar (views/job_folders.py), not the editor's form
        # ...and the status, by Save & issue / Reopen (views/reports.py)
        exclude = ['job_folder', 'job_folder_files', 'status', 'issued_date']
        labels = {
            'document_filename': 'File name',
            'weld_technician': 'Technician',
            'weld_technician_cert': 'Certification',
            'weld_reviewer': 'Reviewed by',
            'weld_reviewer_cert': 'Certification',
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
            # The part the .nde imports recorded, for the Sensitivity block card's Auto-detect
            'scan_part': HiddenInput(),
            # Names from earlier reports (the editor's known-people list) fill in the certification
            'weld_technician': TextInput(attrs={'list': 'known-people', 'autocomplete': 'off', 'data-cert-field': 'weld_technician_cert'}),
            'weld_reviewer': TextInput(attrs={'list': 'known-people', 'autocomplete': 'off', 'data-cert-field': 'weld_reviewer_cert'}),
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
        # Weld editor: empty fields outlined by where their value comes from (fill_marks.js)
        fill_marks.mark_fill(self, fill_marks.REPORT_AUTO_FIELDS, fill_marks.REPORT_USER_FIELDS)


# Setup fields with a unit (converted by static/reports/js/units.js when the Units select changes)
SETUP_UNIT_FIELDS = {
    'length': ['probe_diameter', 'foc_depth', 'x_res', 'y_res', 'scan_length', 'scan_width', 'specimen_od',
               'specimen_thickness', 'specimen_dimensions', 'tr_min', 'tr_max', 'pcs', 'index_offset',
               'weld_root_face', 'weld_root_gap', 'weld_cap_width'],
    'velocity': ['sound_velocity'],
    'per_length': ['encoder_resolution'],
}


def unit_toggle(form, name, fields):
    """
    Marks a Units select so units.js converts `fields` ({kind: [names]}) when it changes. Not
    required: a form posted without it keeps imperial (see UnitsCleanMixin).
    """
    form.fields[name].required = False
    form.fields[name].widget.attrs.update({'data-unit-toggle': json.dumps(fields)})


class UnitsCleanMixin:
    def clean_units(self):
        return self.cleaned_data.get('units') or 'imperial'


def catalogue_choices(form, probe_name, wedge_name):
    """
    Probe / wedge catalogue selects on a form: the wedge list shows only wedges that fit the chosen
    probe (the Beamtool library has many); static/reports/js/catalogue_select.js refreshes it when the
    probe changes and adds type-to-filter boxes. Validation still accepts any wedge.
    """
    probe_field, wedge_field = form.fields[probe_name], form.fields[wedge_name]
    pair = form.prefix or 'form'  # links a probe select to its own wedge select (grid columns sit side by side)
    probe_field.widget.attrs.update({'data-catalogue': 'probe', 'data-catalogue-pair': pair})
    wedge_field.widget.attrs.update({'data-catalogue': 'wedge', 'data-catalogue-pair': pair,
                                     'data-wedges-url': reverse_lazy('scan-plan-wedges')})

    def chosen(name):
        # Unbound: the form's initial (a model form's instance, or e.g. a defaults column's values)
        value = form.data.get(form.add_prefix(name)) if form.is_bound else form.initial.get(name)
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


class SetupForm(UnitsCleanMixin, StyledFormMixin, ModelForm):
    fieldsets_spec = [
        ('Technique', ['title', 'method_description', 'procedure', 'units']),
        ('UT equipment', ['manufacturer', 'scope_platform', 'scope_model', 'scope_serial',
                          'transducer_model', 'transducer_serial', 'probe_diameter']),
        ('Wedge', ['wedge_model', 'wedge_angle']),
        ('UT settings', ['foc_depth', 'wave_propagation', 'freq', 'elements', 'x_res', 'y_res',
                         'scan_length', 'scan_width', 'angle_step', 'angle_range', 'sound_velocity',
                         'gain', 'beam_gain', 'ref_gain', 'voltage']),
        ('Acquisition', ['beam_formation', 'active_elements', 'element_aperture', 'element_step', 'pcs',
                         'scan_pattern', 'encoder_resolution', 'digitizing_frequency', 'pulse_width',
                         'band_pass_filter', 'calibrations', 'gates']),
        ('Specimen', ['specimen_od', 'specimen_thickness', 'specimen_dimensions', 'inspection_material',
                      'inspection_temp']),
        ('Calibration', ['cal_material', 'material_temp', 'cal_block_type', 'cal_block_serial',
                         'surface_prep', 'tr_min', 'tr_max', 'couplant', 'exam_surface']),
        ('Weld form equipment details', ['scope_cal_due', 'module_model', 'module_serial', 'module_cal_due',
                                         'software_version', 'scanner_type', 'scanner_model', 'analysis_software',
                                         'analysis_software_version', 'scan_speed', 'cable_type', 'cable_length',
                                         'wedge_material', 'wedge_curve', 'focal_plane', 'time_base',
                                         'points_quantity', 'smoothing', 'amplitude_range', 'transfer_db',
                                         'scanning_db']),
        ('Source', ['source_file', 'acquisition_date']),
        ('Catalogue probe and wedge (for scan plans)', ['catalogue_probe', 'catalogue_wedge', 'first_element',
                                                        'aperture_elements', 'index_offset', 'wedge_primary_offset',
                                                        'wedge_first_element_height', 'wedge_velocity',
                                                        'wedge_length', 'wedge_height']),
        ('Weld (for scan plans)', ['weld_bevel_angle', 'weld_root_face', 'weld_root_gap', 'weld_cap_width']),
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
            'index_offset': 'Index offset',
        }
        widgets = {
            'wave_propagation': TextInput(attrs={'list': 'wave_propagation_options'}),
            'gates': Textarea(attrs={'rows': 2}),
            'title': TextInput(attrs={'placeholder': 'e.g. HydroFORM, Angle Beam, TFM'}),
            'procedure': TextInput(attrs={'placeholder': 'e.g. 100-UT-031 Rev. 1'}),
            'nde_sheet': HiddenInput(),   # rendered on its own (not in a fieldset) so saving keeps it
        }
        help_texts = {'title': 'Heads this setup\'s "Equipment Details" section. The Introduction\'s technique '
                               'bullet uses the Text library description with this name.',
                      'index_offset': 'Wedge front to the weld centre line.',
                      'weld_cap_width': 'Leave blank to have scan plans calculate it from the bevel.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'catalogue_probe' in self.fields and 'catalogue_wedge' in self.fields:
            catalogue_choices(self, 'catalogue_probe', 'catalogue_wedge')
        if 'units' in self.fields:
            unit_toggle(self, 'units', SETUP_UNIT_FIELDS)
        if 'method_description' in self.fields:
            # Listed by name; picking one fills an empty Method with it (create_report.js)
            field = self.fields['method_description']
            field.label_from_instance = lambda snippet: snippet.name
            field.empty_label = '— Choose —'
            field.widget.attrs['data-method-description'] = ''
        # The long form editor's fill marks (fill_marks.js; only shown where the report type has them)
        fill_marks.mark_fill(self, fill_marks.SETUP_AUTO_FIELDS, fill_marks.SETUP_USER_FIELDS)


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
        fields = ['image', 'scan_id', 'caption', 'description']  # order comes from position on the page
        labels = {'image': 'Scan image', 'scan_id': 'Scan ID', 'caption': 'Label (if not in results table)'}
        widgets = {
            'image': ClearableFileInput(attrs={'accept': 'image/*'}),
            'scan_id': Select(attrs={'class': 'scan-id-select'}),
            'description': Textarea(attrs={'rows': 2}),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fill_marks.mark_fill(self, set(), fill_marks.PERSON_USER_FIELDS)


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


class ClientCodeForm(StyledFormMixin, ModelForm):
    class Meta:
        model = ClientCode
        fields = ['code', 'client', 'location']


class WorkingFolderForm(StyledFormMixin, ModelForm):
    report_type = ChoiceField(choices=report_type_choices, label='Report type')

    class Meta:
        model = WorkingFolder
        fields = ['path', 'report_type', 'is_default']
        labels = {'path': 'Folder', 'is_default': 'Default for this report type'}

    def clean_path(self):
        path = self.cleaned_data['path'].strip().strip('"')
        if not os.path.isdir(path):
            raise ValidationError(f'No folder at {path}.')
        return str(Path(path).resolve())


class TextSnippetForm(StyledFormMixin, ModelForm):
    class Meta:
        model = TextSnippet
        fields = ['kind', 'name', 'title', 'body']
        labels = {'name': 'Name', 'title': 'Bold lead', 'body': 'Text'}
        widgets = {'body': Textarea(attrs={'rows': 8})}


SCAN_PLAN_NUMBERS = (
    'thickness', 'bevel_angle', 'root_gap', 'root_face', 'cap_width', 'haz_width', 'index_offset', 'index_offset_2',
    'exit_point', 'wedge_angle', 'angle_start', 'angle_stop', 'angle_step', 'shear_velocity',
    'bottom_bevel_angle', 'land_depth', 'upper_bevel_angle', 'transition_height', 'root_radius', 'cap_height',
    'root_height', 'counterbore_depth', 'counterbore_length', 'counterbore_taper', 'outside_diameter',
)
# Fields that apply to only some beam directions (scan_plan.js shows them for those): a pipe's OD
# and the wedge's contour for beams round it; a counterbore for beams along it (girth welds)
SCAN_PLAN_BEAM_DIRECTION_FIELDS = {
    'outside_diameter': ['circumferential'],
    'wedge_contour': ['circumferential'],
    'counterbore_depth': ['axial'],
    'counterbore_length': ['axial'],
    'counterbore_taper': ['axial'],
}
# Weld profile fields that apply to only some weld types (scan_plan.js shows them for those)
SCAN_PLAN_WELD_TYPE_FIELDS = {
    'bevel_side': ['single_bevel', 'j_bevel'],
    'bottom_bevel_angle': ['double_v'],
    'land_depth': ['double_v'],
    'upper_bevel_angle': ['compound'],
    'transition_height': ['compound'],
    'root_radius': ['j_bevel', 'u_groove'],
}


# Scan plan fields with a unit: stored in inches (in/µs), shown in mm (m/s) for metric plans
SCAN_PLAN_UNIT_FIELDS = {
    'length': ['thickness', 'root_gap', 'root_face', 'cap_width', 'haz_width', 'index_offset', 'index_offset_2',
               'land_depth', 'transition_height', 'root_radius', 'cap_height', 'root_height', 'counterbore_depth',
               'counterbore_length', 'outside_diameter'],
    'velocity': ['shear_velocity'],
}
UNIT_FACTORS = {'length': 25.4, 'velocity': 25400.0}   # imperial -> metric


class ScanPlanForm(UnitsCleanMixin, StyledFormMixin, ModelForm):
    fieldsets_spec = [
        ('Scan plan', ['name', 'sensitivity_block', 'pipe_size', 'units']),
        ('Weld', ['weld_type', 'bevel_side', 'thickness', 'bevel_angle', 'bottom_bevel_angle', 'land_depth',
                  'upper_bevel_angle', 'transition_height', 'root_radius', 'root_gap', 'root_face', 'cap_width',
                  'cap_height', 'root_height', 'haz_width', 'shear_velocity']),
        ('Pipe', ['beam_direction', 'outside_diameter', 'wedge_contour', 'counterbore_depth', 'counterbore_length',
                  'counterbore_taper']),
        # Laid out by hand (edit_scan_plan.html): each index offset beside its 90 / 270 deg skew boxes
        ('Probe positions', ['index_offset', 'skew_90', 'skew_270', 'index_offset_2', 'skew_90_2', 'skew_270_2']),
        ('Probe and wedge', ['probe_model', 'wedge_model', 'first_element', 'aperture_elements']),
        # Two columns: start / stop angle, then beam legs / angle step under them
        ('Beams', ['angle_start', 'angle_stop', 'legs', 'angle_step']),
        # The reflector table (scan_plan_reflectors.js edits the hidden reflectors field) and its print box
        ('Reflectors', ['print_reflectors']),
        (None, ['notes']),
        # wedge_angle and exit_point are hidden: they come from the selected wedge; mode is the
        # Simple / Advanced switch above the fields
    ]
    # Shown in advanced mode only: simple mode keeps their values (defaults, or what a setup filled)
    ADVANCED_FIELDS = ('root_gap', 'root_face', 'cap_width', 'haz_width', 'shear_velocity', 'first_element',
                       'aperture_elements', 'legs', 'angle_step', 'weld_type', 'bevel_side', 'bottom_bevel_angle',
                       'land_depth', 'upper_bevel_angle', 'transition_height', 'root_radius', 'cap_height',
                       'root_height', 'counterbore_depth', 'counterbore_length', 'counterbore_taper',
                       'beam_direction', 'outside_diameter', 'wedge_contour', 'print_reflectors')
    # A form posted without these keeps the model's default
    OPTIONAL_WITH_DEFAULT = ('weld_type', 'bevel_side', 'bottom_bevel_angle', 'upper_bevel_angle',
                             'transition_height', 'root_radius', 'counterbore_length', 'counterbore_taper',
                             'beam_direction', 'wedge_contour')
    LENGTHS = ('thickness', 'root_gap', 'root_face', 'cap_width', 'haz_width', 'index_offset', 'index_offset_2',
               'exit_point', 'land_depth', 'transition_height', 'root_radius', 'cap_height', 'root_height',
               'counterbore_depth', 'counterbore_length', 'outside_diameter')
    ANGLES = ('bevel_angle', 'wedge_angle', 'angle_start', 'angle_stop', 'bottom_bevel_angle', 'upper_bevel_angle')

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
            'index_offset_2': 'Second index offset',
            'skew_90': '90° skew',
            'skew_270': '270° skew',
            'skew_90_2': '90° skew',
            'skew_270_2': '270° skew',
            'exit_point': 'Exit point',
            'wedge_angle': 'Wedge angle (°)',
            'angle_start': 'Start angle (°)',
            'angle_stop': 'Stop angle (°)',
            'angle_step': 'Angle step (°)',
            'legs': 'Beam legs',
            'notes': 'Notes',
            'sensitivity_block': 'Sensitivity block',
            'shear_velocity': 'Shear velocity',
            'thickness': 'Thickness',
            'units': 'Units',
            'aperture_elements': 'Aperture (elements)',
            'haz_width': 'HAZ width',
            'weld_type': 'Weld type',
            'bevel_side': 'Bevelled side',
            'bottom_bevel_angle': 'Lower bevel (°)',
            'land_depth': 'Land depth',
            'upper_bevel_angle': 'Upper bevel (°)',
            'transition_height': 'Angle change height',
            'root_radius': 'Root radius',
            'cap_height': 'Cap height',
            'root_height': 'Root height',
            'counterbore_depth': 'Counterbore depth',
            'counterbore_length': 'Counterbore length',
            'counterbore_taper': 'Counterbore taper (°)',
            'beam_direction': 'Beam direction',
            'outside_diameter': 'Outside diameter',
            'wedge_contour': 'Wedge bottom',
            'print_reflectors': 'Print reflectors',
        }
        # Shown when the cursor is over an input or its name (components/field_cell.html)
        help_texts = {
            'name': 'A name to find this plan by, e.g. the pipe size and the setup.',
            'sensitivity_block': "Picks a row of the cal block table: fills the thickness, bevel and velocity, "
                                 "and the weld report's Material Information.",
            'pipe_size': 'For your reference, e.g. 6in Sch 40. Not used in the drawing.',
            'units': "Inches or millimetres for the inputs and the drawing's labels. Switching converts the "
                     'values already entered.',
            'thickness': 'Wall thickness at the weld: where the beams skip off the back wall.',
            'bevel_angle': 'Weld prep angle of each side, from vertical (37.5° for a 75° included V).',
            'root_gap': 'Gap between the two lands at the root.',
            'root_face': 'Height of the flat land at the bottom of each bevel.',
            'cap_width': 'Width of the weld cap. Blank = the bevel opening plus 1/16" each side. The wedge front '
                         'never goes closer to the centre line than half of it (the weld toe).',
            'haz_width': 'Parent metal each side of the fusion faces that the beams must also cover, on top of '
                         'the weld itself.',
            'shear_velocity': 'Shear velocity of the part (in/µs, or m/s for metric): sets how the beams refract '
                              'into the part.',
            'index_offset': 'Wedge front to the weld centre line. Blank = the wedge front at the weld toe (half '
                            'the cap width). "Suggest index offset" finds the one that covers the weld + HAZ.',
            'skew_90': 'Draw the probe on the 90° side of the weld at this index offset.',
            'skew_270': 'Draw the probe on the 270° side of the weld (the mirror image) at this index offset.',
            'index_offset_2': 'An optional second probe position, drawn for its ticked skews.',
            'skew_90_2': 'Draw the probe on the 90° side of the weld at the second index offset.',
            'skew_270_2': 'Draw the probe on the 270° side of the weld at the second index offset.',
            'probe_model': 'Phased-array probe from the catalogue: its pitch and element count place the active '
                           'aperture on the wedge.',
            'wedge_model': 'Wedge from the catalogue (only those that fit the probe are listed): its angle, '
                           'velocity and offsets place the probe and where each beam leaves the wedge.',
            'first_element': 'Element the active aperture starts at (element 1 is at the low, back end of the '
                             'wedge).',
            'aperture_elements': 'Number of elements firing together. Blank = all of them.',
            'angle_start': 'Lowest refracted angle of the sectorial scan.',
            'angle_stop': 'Highest refracted angle of the sectorial scan.',
            'angle_step': 'Spacing between the drawn beams. Coverage treats the fan as solid between them.',
            'legs': 'First leg only, or also the second leg after the skip off the back wall. Coverage counts '
                    'every drawn leg.',
            'notes': 'Printed under the scan plan on the report.',
            'weld_type': 'Joint preparation. Single V: one bevel each side. Double V: bevels from both surfaces '
                         'to a land in the wall. Single bevel / J bevel: one side prepped, the other square. '
                         'U groove: a J both sides. Compound bevel: a steeper angle near the root changing to a '
                         'shallower one higher up.',
            'bevel_side': "Which side of the weld has the bevel (the other side is square): the 90° skew's "
                          "side or the 270° skew's.",
            'bottom_bevel_angle': 'Double V: the bevel of the lower (ID side) preparation, from vertical.',
            'land_depth': 'Double V: depth from the OD to the top of the land. Blank = the land in the middle '
                          'of the wall.',
            'upper_bevel_angle': 'Compound bevel: the shallower angle above the change, from vertical (10° for '
                                 'the usual thick-wall compound bevel).',
            'transition_height': 'Compound bevel: height above the land where the bevel angle changes to the '
                                 'upper angle (3/4" for the usual thick-wall compound bevel).',
            'root_radius': 'J bevel / U groove: radius at the bottom of the groove, above the land.',
            'cap_height': 'Cap reinforcement drawn above the surface. Blank = sized to suit the wall.',
            'root_height': 'Root reinforcement drawn below the ID. Blank = sized to suit the wall.',
            'counterbore_depth': 'How much the counterbore takes off the wall at the weld. Blank = no counterbore. '
                                 'The weld and its root sit at the counterbored wall, and the beams skip off it.',
            'counterbore_length': 'Weld centre line to where the counterbore starts to taper back to the full wall.',
            'counterbore_taper': "Angle of the counterbore's taper back to the full wall, from the pipe axis.",
            'beam_direction': 'Axial: the beams run along the pipe, across a girth weld; the section they travel '
                              'in is flat. Circumferential: the beams run round the pipe, across a long seam; '
                              'they enter a curved OD (the refracted angle drifts from nominal) and skip off a '
                              'curved ID.',
            'outside_diameter': "Pipe OD for circumferential beams. Picking a sensitivity block fills its test "
                                "diameter; type over it for a custom OD. Blank = the block's.",
            'wedge_contour': 'Flat: the wedge rocks on the OD and lifts off at its ends (the gap is shown and '
                             'warned about). Contoured: its bottom is machined to the OD.',
            'print_reflectors': "Also draw the reflectors (and each one's best beam) on the report's Scan Plan "
                                'page. They are always drawn here.',
        }
        widgets = {
            'notes': Textarea(attrs={'rows': 2}),
            'mode': RadioSelect(attrs={'class': 'mode-switch-input'}),
            # Text boxes, not number boxes: Up / Down move between fields (arrow_nav.js) rather than
            # stepping the value
            **{name: TextInput(attrs={'inputmode': 'decimal'})
               for name in SCAN_PLAN_NUMBERS + ('first_element', 'aperture_elements')},
            # Set only by the wedge selector (scan_plan.js fills them from the chosen wedge)
            'wedge_angle': HiddenInput(),
            'exit_point': HiddenInput(),
            'wedge_primary_offset': HiddenInput(),
            'wedge_first_element_height': HiddenInput(),
            'wedge_velocity': HiddenInput(),
            'wedge_length': HiddenInput(),
            'wedge_height': HiddenInput(),
            'reflectors': HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        catalogue_choices(self, 'probe_model', 'wedge_model')
        unit_toggle(self, 'units', SCAN_PLAN_UNIT_FIELDS)
        # Not required: a form posted without them keeps simple mode and the default HAZ
        self.fields['mode'].required = self.fields['haz_width'].required = False
        for name in self.OPTIONAL_WITH_DEFAULT:
            self.fields[name].required = False
        self.fields['reflectors'].required = False
        # Which fields each weld type / beam direction uses (scan_plan.js shows only those)
        self.fields['weld_type'].widget.attrs['data-shows-fields'] = json.dumps(SCAN_PLAN_WELD_TYPE_FIELDS)
        self.fields['beam_direction'].widget.attrs['data-shows-fields'] = json.dumps(SCAN_PLAN_BEAM_DIRECTION_FIELDS)
        # Empty fields outlined (fill_marks.js): red = needed to draw, yellow = Fill from setup gives it
        fill_marks.mark_scan_plan(self)
        self.fields['mode'].widget.attrs['class'] = 'mode-switch-input'
        self.fields['legs'].choices = [(ScanPlan.ONE_LEG, '1st leg'), (ScanPlan.TWO_LEGS, '1st and 2nd')]
        for field in self.fields.values():   # every number in the same face
            if field.widget.attrs.get('inputmode') == 'decimal' and 'mono' not in field.widget.attrs['class']:
                field.widget.attrs['class'] += ' mono'
        # A metric plan shows its stored inches as mm (and in/µs as m/s)
        if not self.is_bound and self.instance.units == 'metric':
            for kind, names in SCAN_PLAN_UNIT_FIELDS.items():
                for name in names:
                    value = getattr(self.instance, name)
                    if value is not None:
                        self.initial[name] = round(value * UNIT_FACTORS[kind], 0 if kind == 'velocity' else 2)

    def clean_mode(self):
        return self.cleaned_data.get('mode') or ScanPlan.SIMPLE

    def clean(self):
        data = super().clean()
        if data.get('units') == 'metric':  # stored in inches (in/µs)
            for kind, names in SCAN_PLAN_UNIT_FIELDS.items():
                for name in names:
                    if data.get(name) is not None:
                        data[name] = data[name] / UNIT_FACTORS[kind]
        for name in ('haz_width',) + self.OPTIONAL_WITH_DEFAULT:
            if data.get(name) in (None, '') and name not in self.errors:
                data[name] = ScanPlan._meta.get_field(name).default
        skews = ('skew_90', 'skew_270', 'skew_90_2', 'skew_270_2')
        if not any(data.get(name) for name in skews):
            self.add_error('skew_90', 'Tick at least one skew to draw.')
        if (data.get('skew_90_2') or data.get('skew_270_2')) and data.get('index_offset_2') is None:
            self.add_error('index_offset_2', 'Enter the second index offset, or untick its skews.')
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
        depth = data.get('counterbore_depth')
        if depth is not None and data.get('thickness') and depth >= data['thickness']:
            self.add_error('counterbore_depth', 'The counterbore must leave some wall: make it less than the thickness.')
        if depth and data.get('counterbore_length') is not None and data['counterbore_length'] <= (data.get('root_gap') or 0) / 2:
            self.add_error('counterbore_length', 'The counterbore must reach past the root.')
        if data.get('beam_direction') == ScanPlan.CIRCUMFERENTIAL:
            block = data.get('sensitivity_block')
            od = data.get('outside_diameter') or (
                first_number(block.test_diameter or block.cal_diameter) if block else None)
            if not od:
                self.add_error('outside_diameter', "Enter the pipe's OD, or pick a sensitivity block with a test diameter.")
            elif data.get('thickness') and od <= 2 * data['thickness']:
                self.add_error('outside_diameter', 'The OD must be more than twice the thickness.')
        try:
            data['reflectors'] = scan_plan_reflectors.clean(data.get('reflectors'), data.get('thickness'))
        except ValueError as error:
            self.add_error('reflectors', str(error))
        taper = data.get('counterbore_taper')
        if taper is not None and not 1 <= taper <= 90:
            self.add_error('counterbore_taper', 'Enter a taper from 1 to 90°.')
        return data


# ── Weld form equipment grid (reports/weld_form.py): probe and group columns ──

class GridCellsMixin:
    """Small inputs for grid cells."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, HiddenInput):
                continue
            # Every cell in the same face and size: no `mono` for names in MONO_FIELDS (elements, voltage...)
            classes = ' '.join(c for c in widget.attrs.get('class', '').split() if c != 'mono')
            widget.attrs['class'] = classes.replace('form-control', 'form-control form-control-sm') \
                .replace('form-select', 'form-select form-select-sm')


class ReportProbeForm(GridCellsMixin, StyledFormMixin, ModelForm):
    class Meta:
        model = ReportProbe
        exclude = ['report', 'order']
        widgets = {name: HiddenInput() for name in (
            'wedge_primary_offset', 'wedge_first_element_height', 'wedge_velocity', 'wedge_length', 'wedge_height',
            'source_file')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        catalogue_choices(self, 'catalogue_probe', 'catalogue_wedge')
        fill_marks.mark_fill(self, fill_marks.PROBE_AUTO_FIELDS, fill_marks.PROBE_USER_FIELDS)


class ReportGroupForm(GridCellsMixin, StyledFormMixin, ModelForm):
    # Which probe column the group uses: the probe form's index in the probes formset, so a group
    # can use a probe added in the same save (the view resolves it)
    probe_column = ChoiceField(required=False, label='Probe')

    class Meta:
        model = ReportGroup
        exclude = ['report', 'order', 'probe', 'not_applicable', 'label']   # headed Group 1, 2... as on the form
        widgets = {'source_file': HiddenInput()}

    def __init__(self, *args, probe_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        # 'na': the group's column is N/A (see ReportGroup.not_applicable)
        self.fields['probe_column'].choices = [('', '—'), (weld_form.NOT_USED, 'N/A')] + list(probe_choices)
        if not self.is_bound and self.instance.not_applicable:
            self.initial['probe_column'] = weld_form.NOT_USED
        elif not self.is_bound and self.instance.probe_id is not None:
            self.initial['probe_column'] = str(self.instance.probe.order)
        fill_marks.mark_fill(self, fill_marks.GROUP_AUTO_FIELDS, fill_marks.GROUP_USER_FIELDS)


ProbeFormSet = inlineformset_factory(Report, ReportProbe, form=ReportProbeForm, extra=0, can_delete=True, can_order=True)
GroupFormSet = inlineformset_factory(Report, ReportGroup, form=ReportGroupForm, extra=0, can_delete=True, can_order=True)


def equipment_formsets(data=None, instance=None):
    """(probes formset, groups formset) for the weld form's grid; groups choose among probe columns."""
    probes = ProbeFormSet(data, instance=instance, prefix='probes')
    count = int(data.get('probes-TOTAL_FORMS', 0)) if data is not None else len(probes.forms)
    choices = [(str(i), f'P{i + 1}') for i in range(max(count, weld_form.MAX_PROBES))]
    groups = GroupFormSet(data, instance=instance, prefix='groups', form_kwargs={'probe_choices': choices})
    return probes, groups
