from django import forms
from reports.forms import StyledFormMixin
from .models import CalibrationBlock, Encoder, Probe, ProbeModel, Scope, SensitivityBlock, WedgeModel


class ScopeForm(StyledFormMixin, forms.ModelForm):
    fieldsets_spec = [
        ('Instrument', ['name', 'manufacturer', 'model', 'serial_number', 'instrument_software_version', 'scanner_type']),
        ('Module / pulser', ['module_model', 'module_serial', 'module_cal_due']),
        ('Analysis software', ['software', 'software_version']),
        ('Calibration', ['calibration_date', 'calibration_due_date']),
    ]

    class Meta:
        model = Scope
        fields = '__all__'
        widgets = {
            'calibration_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'calibration_due_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'module_cal_due': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }


class ProbeForm(StyledFormMixin, forms.ModelForm):
    fieldsets_spec = [
        ('Probe', ['catalogue', 'serial_number']),
        ('Details (filled from the catalogue model when left blank)',
         ['manufacturer', 'model', 'frequency', 'elements', 'diameter']),
        ('Element check', ['inactive_elements', 'defective_elements', 'previous_inactive_elements',
                           'previous_defective_elements', 'calibration_obtainable']),
    ]

    class Meta:
        model = Probe
        fields = '__all__'

    def save(self, commit=True):
        probe = super().save(commit=False)
        probe.fill_from_catalogue()
        if commit:
            probe.save()
        return probe


class CalibrationBlockForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CalibrationBlock
        fields = '__all__'


class SensitivityBlockForm(StyledFormMixin, forms.ModelForm):
    fieldsets_spec = [
        ('Pipe size', ['pipe_size', 'test_diameter', 'test_thickness', 'test_sch_nom', 'bevel_geometry', 'surface_test']),
        ('Calibration standard', ['serial_number', 'block_type', 'material', 'cal_diameter', 'cal_sch_nom',
                                  'cal_thickness', 'reflector_depth', 'surface_cal', 'temperature']),
        ('Velocities and scanning', ['velocity_shear', 'velocity_long', 'couplant', 'encoder', 'encoder_steps',
                                     'scan_res', 'scan_speed']),
        (None, ['notes']),
    ]

    class Meta:
        model = SensitivityBlock
        fields = '__all__'


class EncoderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Encoder
        fields = '__all__'


class ProbeModelForm(StyledFormMixin, forms.ModelForm):
    fieldsets_spec = [
        ('Model', ['model', 'series', 'manufacturer', 'item_number']),
        ('Array (mm)', ['frequency', 'elements', 'pitch', 'aperture', 'elevation']),
        ('Housing (mm)', ['length', 'width', 'height']),
        ('Source', ['source', 'notes']),
    ]

    class Meta:
        model = ProbeModel
        fields = '__all__'
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class WedgeModelForm(StyledFormMixin, forms.ModelForm):
    fieldsets_spec = [
        ('Model', ['model', 'manufacturer', 'probe_series', 'probe_fit', 'refracted_angle', 'wave_type', 'sweep']),
        ('Size (mm)', ['length', 'width', 'width_wings', 'height', 'bottom_face', 'part_diameter']),
        ('Geometry for the scan plan', ['wedge_angle', 'velocity', 'first_element_height', 'primary_offset',
                                        'secondary_offset', 'roof_angle']),
        ('Source', ['source', 'notes']),
    ]

    class Meta:
        model = WedgeModel
        fields = '__all__'
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class CatalogueImportForm(forms.Form):
    file = forms.FileField(label='File', help_text='OmniScan / OmniPC .nde file, or Beamtool PATransducers.csv / PAWedges.csv.')
