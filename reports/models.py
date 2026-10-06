import os

from django.db import models

from .weld_form import KIND_CHOICES as WELD_KIND_CHOICES, PAUT as WELD_PAUT, material_fields

class Report(models.Model):
    """
    The reports model is used to store user input data with specific job information.
    """
    # Report type key from reports/report_types.py (picks the Word template and visible inputs)
    report_type = models.CharField(max_length=50, default='paut_long')
    updated_at = models.DateTimeField(auto_now=True, null=True)

    # Project File Name
    document_filename = models.CharField(max_length=200, blank=True)

    # Project Information
    document_title = models.TextField(blank=True)
    client = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    work_order = models.CharField(max_length=100, blank=True)
    project_number = models.CharField(max_length=100, blank=True)
    report_date = models.DateField(blank=True, null=True)
    test_date = models.DateField(blank=True, null=True)  # test start date
    test_end_date = models.DateField(blank=True, null=True)
    project_type = models.CharField(max_length=200, blank=True)
    procedure = models.CharField(max_length=200, blank=True)

    # Weld form header (Excel weld report)
    address = models.CharField(max_length=300, blank=True)
    contractor = models.CharField(max_length=200, blank=True)
    item_description = models.CharField(max_length=300, blank=True)
    exam_code = models.CharField(max_length=200, blank=True)
    acceptance_standard = models.CharField(max_length=200, blank=True)
    procedure_rev = models.CharField(max_length=50, blank=True)

    # Weld form calibration times and notes
    cal_time_initial = models.CharField(max_length=20, blank=True)
    cal_time_check1 = models.CharField(max_length=20, blank=True)
    cal_time_check2 = models.CharField(max_length=20, blank=True)
    cal_time_out = models.CharField(max_length=20, blank=True)
    # Weld form: its two signature lines (the long form lists people with roles instead)
    weld_technician = models.CharField('Technician', max_length=200, blank=True)
    weld_technician_cert = models.CharField('Technician certification', max_length=200, blank=True)
    weld_reviewer = models.CharField('Reviewed by', max_length=200, blank=True)
    weld_reviewer_cert = models.CharField('Reviewer certification', max_length=200, blank=True)
    notes = models.TextField(blank=True)
    scan_plan = models.ForeignKey('ScanPlan', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports')

    # Weld form: the testing instrument (one per report; reports/weld_form.py INSTRUMENT_ROWS)
    inst_name = models.CharField('Testing instrument', max_length=100, blank=True)
    inst_manufacturer = models.CharField('Manufacturer', max_length=100, blank=True)
    inst_model = models.CharField('Model', max_length=100, blank=True)
    inst_serial = models.CharField('S/N', max_length=100, blank=True)
    inst_cal_due = models.CharField('Cal. due date', max_length=50, blank=True)
    inst_module_model = models.CharField('Module model', max_length=100, blank=True)
    inst_module_serial = models.CharField('Module S/N', max_length=100, blank=True)
    inst_module_cal_due = models.CharField('Module cal. due date', max_length=50, blank=True)
    inst_software_version = models.CharField('Software version', max_length=50, blank=True)
    inst_scanner_type = models.CharField('Scanner type', max_length=100, blank=True)
    inst_scanner_model = models.CharField('Scanner make / model', max_length=100, blank=True)
    inst_analysis_software = models.CharField('Analysis software', max_length=100, blank=True)
    inst_analysis_software_version = models.CharField('Analysis software version', max_length=50, blank=True)
    inst_encoder_cal = models.CharField('Encoder cal. (steps/in)', max_length=100, blank=True)
    inst_scan_res = models.CharField('Scan res. (in)', max_length=50, blank=True)
    inst_scan_speed = models.CharField('Speed (in/sec)', max_length=50, blank=True)

    # Executive Summary
    examination_scope = models.TextField(blank=True)
    executive_summary = models.TextField(blank=True)
    
    # Job Scope, References and Method
    asset_description = models.TextField(blank=True)
    equipment_id = models.CharField(max_length=200, blank=True)
    equipment_overview = models.TextField(blank=True)
    work_scope = models.TextField(blank=True)
    x_axis_reference = models.CharField(max_length=200, blank=True)
    y_axis_reference = models.CharField(max_length=200, blank=True)
    # One technique per line; used for the Introduction bullets only when no setup has a Technique title
    ut_method = models.TextField(blank=True)

    # Discussion; blank uses the text library's standard Discussion
    discussion = models.TextField(blank=True)

    # Weld form: Sensitivity block & test material. The block picked from the library fills the
    # card's fields (weld_form.material_fields, added below), which can then be edited
    sensitivity_block = models.ForeignKey('equipment.SensitivityBlock', on_delete=models.SET_NULL, null=True,
                                          blank=True, related_name='reports')
    # The part as the .nde imports recorded it, for Auto-detect: {od, thickness (in), material,
    # shear_velocity, long_velocity (in/µs), bevel_angle (°), source}
    scan_part = models.JSONField(null=True, blank=True)
    # The job folder the report was made from and is saved into (reports/services/job_folder.py),
    # and the files the app wrote there (only those are ever replaced)
    job_folder = models.CharField(max_length=500, blank=True)
    job_folder_files = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.pk} | {self.document_filename}"

    @property
    def prepared_by_names(self):
        return ', '.join(p.name for p in self.people.all() if p.prepared)


# The Sensitivity block & test material card's fields (one per cell of the weld form's Material
# Information, Additional Block(s) and TCG Parameters; reports/weld_form.py)
for _name, _label in material_fields():
    Report.add_to_class(_name, models.CharField(_label, max_length=100, blank=True))


class ScanPlan(models.Model):
    """
    Scan plan for a butt weld (single V, double V, bevel, J, U or compound prep, optional
    counterbore), drawn by reports/services/scan_plan/ and printed
    on the weld report's Scan Plan page. Saved on its own so one plan serves every report for the
    same pipe size and setup. Lengths are in inches, angles in degrees.
    """
    ONE_LEG, TWO_LEGS = 1, 2
    LEG_CHOICES = [(ONE_LEG, 'First leg only'), (TWO_LEGS, 'First and second leg')]
    SKEW_90, SKEW_270 = 90, 270
    SIMPLE, ADVANCED = 'simple', 'advanced'

    name = models.CharField(max_length=100)
    # Simple shows the few inputs a plain butt weld needs; advanced shows them all
    mode = models.CharField(max_length=10, choices=[(SIMPLE, 'Simple'), (ADVANCED, 'Advanced')], default=SIMPLE)
    pipe_size = models.CharField(max_length=100, blank=True, help_text='For your reference, e.g. 6in Sch 40.')
    sensitivity_block = models.ForeignKey(
        'equipment.SensitivityBlock', on_delete=models.SET_NULL, null=True, blank=True, related_name='scan_plans',
        help_text="Fills thickness, pipe size, bevel and velocity, and the weld report's Material Information.")
    probe_model = models.ForeignKey('equipment.ProbeModel', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='scan_plans', verbose_name='Probe')
    wedge_model = models.ForeignKey('equipment.WedgeModel', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='scan_plans', verbose_name='Wedge')
    first_element = models.PositiveIntegerField(default=1)
    aperture_elements = models.PositiveIntegerField(null=True, blank=True, help_text='Blank = all elements.')
    shear_velocity = models.FloatField(default=0.1276, help_text='Part shear velocity, in/µs.')

    # Weld
    thickness = models.FloatField()
    bevel_angle = models.FloatField(default=37.5, help_text='Each side, from vertical.')
    root_gap = models.FloatField(default=0.0625)
    root_face = models.FloatField(default=0.0625)
    cap_width = models.FloatField(null=True, blank=True, help_text='Blank = bevel opening plus 1/16" each side.')
    # Inspection volume for coverage: the weld plus this band of parent metal beyond each fusion face
    haz_width = models.FloatField(default=0.25)

    # Weld profile (advanced). bevel_angle is the V's angle, the double V's top, the compound
    # bevel's lower (root) angle and the J / U side wall angle; all angles from vertical.
    SINGLE_V, DOUBLE_V, SINGLE_BEVEL, J_BEVEL, U_GROOVE, COMPOUND = (
        'single_v', 'double_v', 'single_bevel', 'j_bevel', 'u_groove', 'compound')
    WELD_TYPE_CHOICES = [(SINGLE_V, 'Single V'), (DOUBLE_V, 'Double V'), (SINGLE_BEVEL, 'Single bevel'),
                         (J_BEVEL, 'J bevel'), (U_GROOVE, 'U groove'), (COMPOUND, 'Compound bevel')]
    weld_type = models.CharField(max_length=20, choices=WELD_TYPE_CHOICES, default=SINGLE_V)
    # Single bevel / J bevel: the side with the prep (the other is square); 90 = the 90 deg skew's side
    bevel_side = models.PositiveSmallIntegerField(choices=[(SKEW_90, '90° side'), (SKEW_270, '270° side')],
                                                  default=SKEW_270)
    bottom_bevel_angle = models.FloatField(default=37.5)                  # double V's lower prep
    land_depth = models.FloatField(null=True, blank=True)                 # double V: OD to the land; blank = middle
    upper_bevel_angle = models.FloatField(default=10.0)                   # compound bevel's upper angle
    transition_height = models.FloatField(default=0.75)                   # compound: land top to the angle change
    root_radius = models.FloatField(default=0.25)                         # J / U groove bottom radius
    cap_height = models.FloatField(null=True, blank=True)                 # blank = drawn to suit the wall
    root_height = models.FloatField(null=True, blank=True)
    # Counterbore: the bore machined into each pipe's ID at the joint; thins the wall to
    # thickness - depth within `length` of the weld centre line, tapering back at `taper` deg
    counterbore_depth = models.FloatField(null=True, blank=True)
    counterbore_length = models.FloatField(default=1.0)
    counterbore_taper = models.FloatField(default=30.0)

    # Beam direction: axial (across a girth weld; the section the beams travel in is flat) or
    # circumferential (across a long seam: the beams travel round the pipe's curved wall)
    AXIAL, CIRCUMFERENTIAL = 'axial', 'circumferential'
    beam_direction = models.CharField(max_length=20, default=AXIAL, choices=[
        (AXIAL, 'Axial (girth weld)'), (CIRCUMFERENTIAL, 'Circumferential (long seam)')])
    # Pipe OD for circumferential beams: filled from the sensitivity block's test diameter, or typed
    outside_diameter = models.FloatField(null=True, blank=True)
    FLAT_WEDGE, CONTOURED_WEDGE = 'flat', 'contoured'
    wedge_contour = models.CharField(max_length=10, default=FLAT_WEDGE, choices=[
        (FLAT_WEDGE, 'Flat'), (CONTOURED_WEDGE, 'Contoured to the OD')])

    # Reflectors to check the beams against (reports/services/scan_plan/reflectors.py): a list of
    # {kind, label, side, distance, depth, size, angle}, lengths in inches. Drawn in the editor;
    # on the printed drawing only with print_reflectors.
    reflectors = models.JSONField(default=list, blank=True)
    print_reflectors = models.BooleanField(default=False)

    # Probe position and beams
    index_offset = models.FloatField(null=True, blank=True,
                                     help_text='Wedge front to weld centre line. Blank = the weld toe (half the cap width).')
    # Skews drawn at the index offset (90 deg: probe on one side of the weld; 270 deg: the other)
    skew_90 = models.BooleanField(default=True)
    skew_270 = models.BooleanField(default=True)
    # An optional second probe position, with its own skews
    index_offset_2 = models.FloatField(null=True, blank=True)
    skew_90_2 = models.BooleanField(default=False)
    skew_270_2 = models.BooleanField(default=False)
    exit_point = models.FloatField(default=0.45, help_text='Wedge front back to the beam exit (index) point.')
    wedge_angle = models.FloatField(default=36.0)
    # The wedge geometry from the .nde of the setup this plan was filled from (mm, m/s); when set,
    # the drawing uses it with the catalogue wedge's size. Cleared when another wedge is picked.
    wedge_primary_offset = models.FloatField(null=True, blank=True)
    wedge_first_element_height = models.FloatField(null=True, blank=True)
    wedge_velocity = models.FloatField(null=True, blank=True)
    wedge_length = models.FloatField(null=True, blank=True)
    wedge_height = models.FloatField(null=True, blank=True)
    angle_start = models.FloatField(default=40.0)
    angle_stop = models.FloatField(default=70.0)
    angle_step = models.FloatField(default=1.0)
    legs = models.PositiveSmallIntegerField(choices=LEG_CHOICES, default=TWO_LEGS)
    # Lengths are stored in inches (and velocity in in/µs); with metric the editor shows and takes
    # mm (and m/s) and the drawing labels mm
    units = models.CharField(max_length=10, choices=[('imperial', 'Imperial (in)'), ('metric', 'Metric (mm)')],
                             default='imperial')

    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def _length_text(self, inches):
        if inches is None:
            return ''
        return f'{inches * 25.4:.2f} mm' if self.units == 'metric' else f'{inches:.3f}"'

    @property
    def thickness_text(self):
        return self._length_text(self.thickness)

    @property
    def index_offset_text(self):
        return self._length_text(self.index_offset)

    @property
    def drawings(self):
        """
        [(position, index offset in inches or None, skew)] for each drawing: position 1 or 2, and a
        skew of 90 or 270 deg for each ticked box (1 to 4 drawings).
        """
        out = []
        for position, offset, skews in ((1, self.index_offset, (self.skew_90, self.skew_270)),
                                        (2, self.index_offset_2, (self.skew_90_2, self.skew_270_2))):
            for skew, ticked in zip((self.SKEW_90, self.SKEW_270), skews):
                if ticked:
                    out.append((position, offset, skew))
        return out


class ReportDefaults(models.Model):
    """
    Preferences › Defaults: a named set of values a new report starts with, for its report fields and
    for each new setup block (or, on the weld form, its prefilled probe and group columns). A report type can have several (e.g. per client); the one marked
    in use is what new reports of that type start from. Kept apart from reports so a defaults set
    is never listed or generated as a report. Values are {field name: value} (FKs as their pk).
    """
    name = models.CharField(max_length=100, default='Standard')
    report_type = models.CharField(max_length=50)
    in_use = models.BooleanField('Used for new reports', default=False)
    report_values = models.JSONField(default=dict, blank=True)
    setup_values = models.JSONField(default=dict, blank=True)
    # Weld form grid: the probe and group columns a new report starts with, as lists of
    # {field: value}; a group's 'probe_column' is the index of its probe in probe_columns
    probe_columns = models.JSONField(default=list, blank=True)
    group_columns = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['report_type', 'name']
        constraints = [
            models.UniqueConstraint(fields=['report_type', 'name'], name='unique_defaults_name_per_type'),
            models.UniqueConstraint(fields=['report_type'], condition=models.Q(in_use=True),
                                    name='one_defaults_in_use_per_type'),
        ]

    def __str__(self):
        return self.name

    def use(self):
        """Make this the set new reports of its type start from."""
        ReportDefaults.objects.filter(report_type=self.report_type, in_use=True).exclude(pk=self.pk).update(in_use=False)
        if not self.in_use:
            self.in_use = True
            self.save(update_fields=['in_use', 'updated_at'])


class TextSnippet(models.Model):
    """
    Reusable report text, edited in the app's Text library. Technique descriptions are used for
    the report's technique bullets: a setup whose Technique title matches `name` (ignoring case)
    gets '<title> – <body>'. The Discussion snippet named 'default' is used when a report has
    no Discussion of its own.
    """
    TECHNIQUE = 'technique'
    DISCUSSION = 'discussion'
    KIND_CHOICES = [(TECHNIQUE, 'Technique description'), (DISCUSSION, 'Discussion')]
    DEFAULT_DISCUSSION = 'default'

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=TECHNIQUE)
    name = models.CharField(max_length=100, help_text='Technique: the setup Technique title it applies to, e.g. HydroFORM. '
                                                      "Discussion: 'default' is used for new reports.")
    title = models.CharField(max_length=200, blank=True, help_text='Bold lead of the bullet, e.g. ENCODED HydroFORM 0-degree PAUT')
    body = models.TextField(blank=True)

    class Meta:
        ordering = ['kind', 'name']
        constraints = [models.UniqueConstraint(fields=['kind', 'name'], name='unique_snippet_kind_name')]

    def __str__(self):
        return f'{self.get_kind_display()}: {self.name}'


class ReportPerson(models.Model):
    """Someone on the report: listed on the cover under each role they hold."""
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='people')
    name = models.CharField(max_length=200)
    certification = models.CharField(max_length=200, blank=True)
    prepared = models.BooleanField('Prepared by', default=False)
    examined = models.BooleanField('Examined by', default=False)
    reviewed = models.BooleanField('Reviewed by', default=False)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'pk']

    def __str__(self):
        return self.name


class ReportProbe(models.Model):
    """
    A probe column of the weld form's equipment grid: the probe and wedge hardware. Groups point
    to the probe they use (one probe can drive several groups).
    """
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='probes')
    order = models.IntegerField(default=0)
    label = models.CharField(max_length=50, blank=True, help_text='Column heading, e.g. 90°, 270°, 0°, Trans.')
    kind = models.CharField(max_length=20, choices=WELD_KIND_CHOICES, default=WELD_PAUT)
    make = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    frequency = models.CharField(max_length=50, blank=True)
    cable_type = models.CharField(max_length=100, blank=True)
    cable_length = models.CharField(max_length=50, blank=True)
    serial = models.CharField('Probe S/N', max_length=100, blank=True)
    wedge_material = models.CharField("Wedge mat'l", max_length=100, blank=True)
    wedge_model = models.CharField(max_length=100, blank=True)
    wedge_angle = models.CharField('Wedge ref. angle', max_length=50, blank=True)
    wedge_diameter = models.CharField('Wedge dia.', max_length=50, blank=True)
    wedge_curve = models.CharField('Wedge curve type', max_length=50, blank=True)
    probe_check = models.CharField(max_length=50, blank=True)
    # Catalogue links and the .nde wedge geometry (mm, m/s), for scan plans
    catalogue_probe = models.ForeignKey('equipment.ProbeModel', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='report_probes', verbose_name='Catalogue probe')
    catalogue_wedge = models.ForeignKey('equipment.WedgeModel', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='report_probes', verbose_name='Catalogue wedge')
    wedge_primary_offset = models.FloatField(null=True, blank=True)
    wedge_first_element_height = models.FloatField(null=True, blank=True)
    wedge_velocity = models.FloatField(null=True, blank=True)
    wedge_length = models.FloatField(null=True, blank=True)
    wedge_height = models.FloatField(null=True, blank=True)
    # The .nde (or saved setup) that filled the column; blank = typed in or a default, so an import
    # may fill it
    source_file = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['order', 'pk']

    def __str__(self):
        return f'Probe {self.order + 1}: {self.model or self.get_kind_display()}'


class ReportGroup(models.Model):
    """A group column of the weld form's equipment grid: the settings of one inspection group."""
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='groups')
    order = models.IntegerField(default=0)
    label = models.CharField(max_length=50, blank=True, help_text='Column heading, e.g. 0°, Trans.')
    probe = models.ForeignKey(ReportProbe, on_delete=models.SET_NULL, null=True, blank=True, related_name='groups')
    scan = models.CharField(max_length=50, blank=True)
    wave_mode = models.CharField(max_length=50, blank=True)
    angles = models.CharField('Angle(s)', max_length=50, blank=True)
    elements = models.CharField('Ele start / stop', max_length=50, blank=True)
    angle_increment = models.CharField(max_length=50, blank=True)
    vpa = models.CharField('Ele per VPA / VPA index', max_length=50, blank=True)
    focal_plane = models.CharField(max_length=50, blank=True)
    focal_distance = models.CharField(max_length=50, blank=True)
    time_base = models.CharField('Time base, start / stop', max_length=100, blank=True)
    voltage = models.CharField('Pulser voltage', max_length=50, blank=True)
    points_quantity = models.CharField(max_length=50, blank=True)
    smoothing = models.CharField(max_length=50, blank=True)
    filter = models.CharField('Filter settings', max_length=50, blank=True)
    amplitude_range = models.CharField(max_length=50, blank=True)
    reference_db = models.CharField('Reference dB', max_length=50, blank=True)
    transfer_db = models.CharField('Transfer dB', max_length=50, blank=True)
    scanning_db = models.CharField('Scanning dB', max_length=50, blank=True)
    first_element = models.PositiveIntegerField(null=True, blank=True)
    aperture_elements = models.PositiveIntegerField('Aperture (elements)', null=True, blank=True)
    # N/A on the Probe select: the column stays in its place with every cell N/A
    not_applicable = models.BooleanField(default=False)
    # The .nde (or saved setup) that filled the column; blank = typed in or a default, so an import
    # may fill it
    source_file = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['order', 'pk']

    def __str__(self):
        return f'Group {self.order + 1}'


class Setup(models.Model):
    """
    The setup model will store equipment specific information to be recalled as needed.
    """
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='setups', null=True, blank=True)

    # Technique: heads the report's "Equipment Details: <title>" section
    title = models.CharField(max_length=100, blank=True)
    procedure = models.CharField(max_length=200, blank=True)

    # UT Equipment Information
    manufacturer = models.CharField(max_length=200, blank=True, default="Evident")
    scope_platform = models.CharField(max_length=200, blank=True)
    scope_model = models.CharField(max_length=200, blank=True)
    scope_serial = models.CharField(max_length=200, blank=True)
    transducer_model = models.CharField(max_length=200, blank=True)
    transducer_serial = models.CharField(max_length=200, blank=True)
    probe_diameter = models.CharField(max_length=100, blank=True)

    # Wedge Information
    wedge_model = models.CharField(max_length=200, blank=True)
    wedge_angle = models.CharField(max_length=100, blank=True)

    # UT Setup Information
    foc_depth = models.CharField(max_length=100, blank=True)
    wave_propagation = models.CharField(max_length=100, blank=True)
    freq = models.CharField(max_length=100, blank=True)
    elements = models.CharField(max_length=100, blank=True)
    x_res = models.CharField(max_length=100, blank=True)
    y_res = models.CharField(max_length=100, blank=True)
    scan_length = models.CharField(max_length=100, blank=True)
    scan_width = models.CharField(max_length=100, blank=True)
    angle_step = models.CharField(max_length=50, blank=True)
    angle_range = models.CharField(max_length=50, blank=True)
    sound_velocity = models.CharField(max_length=100, blank=True)
    gain = models.CharField(max_length=100, blank=True)
    beam_gain = models.CharField(max_length=100, blank=True)
    ref_gain = models.CharField(max_length=100, blank=True)
    voltage = models.CharField(max_length=100, blank=True)

    # Acquisition / beam formation
    beam_formation = models.CharField(max_length=100, blank=True)
    active_elements = models.CharField(max_length=50, blank=True)
    element_aperture = models.CharField(max_length=50, blank=True)
    element_step = models.CharField(max_length=50, blank=True)
    pcs = models.CharField(max_length=50, blank=True)
    scan_pattern = models.CharField(max_length=100, blank=True)
    encoder_resolution = models.CharField(max_length=200, blank=True)
    digitizing_frequency = models.CharField(max_length=50, blank=True)
    pulse_width = models.CharField(max_length=50, blank=True)
    band_pass_filter = models.CharField(max_length=100, blank=True)
    gates = models.TextField(blank=True)
    calibrations = models.CharField(max_length=200, blank=True)

    # Specimen Information
    specimen_od = models.CharField(max_length=100, blank=True)
    specimen_thickness = models.CharField(max_length=100, blank=True)
    specimen_dimensions = models.CharField(max_length=100, blank=True)

    # Calibration information
    cal_material = models.CharField(max_length=200, blank=True)
    material_temp = models.CharField(max_length=50, blank=True)
    cal_block_type = models.CharField(max_length=200, blank=True)
    cal_block_serial = models.CharField(max_length=200, blank=True)
    surface_prep = models.CharField(max_length=200, blank=True)
    tr_min = models.CharField(max_length=50, blank=True)
    tr_max = models.CharField(max_length=50, blank=True)

    # Source data file (filled by NDE import)
    source_file = models.CharField(max_length=255, blank=True)
    acquisition_date = models.CharField(max_length=50, blank=True)

    # Unit system of this setup's measured values (lengths, velocity, encoder steps)
    IMPERIAL, METRIC = 'imperial', 'metric'
    UNIT_CHOICES = [(IMPERIAL, 'Imperial (in)'), (METRIC, 'Metric (mm)')]
    units = models.CharField(max_length=10, choices=UNIT_CHOICES, default=IMPERIAL)

    # Weld form equipment details (100-UTFORM-010): instrument, probe / wedge, group settings,
    # material; usually filled from the report type's defaults
    scope_cal_due = models.CharField('Instrument cal. due', max_length=50, blank=True)
    module_model = models.CharField('Module model', max_length=100, blank=True)
    module_serial = models.CharField('Module S/N', max_length=100, blank=True)
    module_cal_due = models.CharField('Module cal. due', max_length=50, blank=True)
    software_version = models.CharField('Software version', max_length=50, blank=True)
    scanner_type = models.CharField('Scanner type', max_length=100, blank=True)
    scanner_model = models.CharField('Scanner make / model', max_length=100, blank=True)
    analysis_software = models.CharField('Analysis software', max_length=100, blank=True)
    analysis_software_version = models.CharField('Analysis software version', max_length=50, blank=True)
    scan_speed = models.CharField('Scan speed', max_length=50, blank=True)
    cable_type = models.CharField('Cable type', max_length=100, blank=True)
    cable_length = models.CharField('Cable length', max_length=50, blank=True)
    wedge_material = models.CharField('Wedge material', max_length=100, blank=True)
    wedge_curve = models.CharField('Wedge curve type', max_length=50, blank=True)
    focal_plane = models.CharField('Focal plane', max_length=50, blank=True)
    time_base = models.CharField('Time base start / stop', max_length=100, blank=True)
    points_quantity = models.CharField('Points quantity', max_length=50, blank=True)
    smoothing = models.CharField(max_length=50, blank=True)
    amplitude_range = models.CharField('Amplitude range', max_length=50, blank=True)
    transfer_db = models.CharField('Transfer dB', max_length=50, blank=True)
    scanning_db = models.CharField('Scanning dB', max_length=50, blank=True)
    couplant = models.CharField(max_length=100, blank=True)
    exam_surface = models.CharField('Exam surface (ID / OD)', max_length=50, blank=True)

    # Wedge front to the weld centre line (from the .nde file's wedge position), for scan plans
    index_offset = models.CharField(max_length=50, blank=True)

    # Weld geometry from the .nde file's weld definition (for scan plans)
    weld_bevel_angle = models.CharField('Bevel angle (°)', max_length=20, blank=True)
    weld_root_face = models.CharField('Root face (land)', max_length=20, blank=True)
    weld_root_gap = models.CharField('Root gap', max_length=20, blank=True)
    weld_cap_width = models.CharField('Cap width', max_length=20, blank=True)

    # Wedge geometry as the .nde file records it (always mm and m/s, whatever the units above);
    # scan plans filled from this setup draw with it
    wedge_primary_offset = models.FloatField('Wedge primary offset (mm)', null=True, blank=True)
    wedge_first_element_height = models.FloatField('First element height (mm)', null=True, blank=True)
    wedge_velocity = models.FloatField('Wedge velocity (m/s)', null=True, blank=True)
    wedge_length = models.FloatField('Wedge length (mm)', null=True, blank=True)
    wedge_height = models.FloatField('Wedge height (mm)', null=True, blank=True)

    # Catalogue probe / wedge (matched on NDE import) and the aperture used, for scan plans
    catalogue_probe = models.ForeignKey('equipment.ProbeModel', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='setups', verbose_name='Catalogue probe')
    catalogue_wedge = models.ForeignKey('equipment.WedgeModel', on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='setups', verbose_name='Catalogue wedge')
    first_element = models.PositiveIntegerField(null=True, blank=True)
    aperture_elements = models.PositiveIntegerField('Aperture (elements)', null=True, blank=True)

    order = models.IntegerField(default=0)

    def __str__(self):
        return f"Setup {self.pk} - {self.report}"


class SetupImage(models.Model):
    """Calibration screenshots shown under a setup's Equipment Details section."""
    setup = models.ForeignKey(Setup, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='setup_images/')
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order', 'pk']

    def __str__(self):
        return f"Image {self.pk} for Setup {self.setup_id}"


class ReportImage(models.Model):
    SCAN = 'scan'
    DRAWING = 'drawing'
    INDICATION = 'indication'
    KIND_CHOICES = [
        (SCAN, 'Scan image (photo summary)'),
        (DRAWING, 'Equipment drawing'),
        (INDICATION, 'Indication image (weld form)'),
    ]

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='images')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=SCAN)
    image = models.ImageField(upload_to='report_images/')
    # Drawings: the drawing's title. Scan images: optional label when not tied to a results row.
    caption = models.CharField(max_length=200, blank=True)
    # Scan images: the results-table Scan ID this image belongs to (matched by text, because
    # results rows are recreated on every save); its comments come from that row. Indication
    # images: the key of the weld form indication it belongs to (saved after the row's cells).
    scan_id = models.CharField(max_length=200, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Image {self.pk} for Report {self.report_id}"


class ResultsTable(models.Model):
    report = models.OneToOneField(Report, on_delete=models.CASCADE, related_name='results_table')
    columns = models.JSONField(default=list)

    def __str__(self):
        return f"ResultsTable for Report {self.report_id}"


class ResultsRow(models.Model):
    table = models.ForeignKey(ResultsTable, on_delete=models.CASCADE, related_name='rows')
    cells = models.JSONField(default=list)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']


class ResultsTablePreset(models.Model):
    name = models.CharField(max_length=100, unique=True)
    columns = models.JSONField(default=list)

    def __str__(self):
        return self.name


class ClientCode(models.Model):
    """
    A client abbreviation as job folders start with it (PPI-32-27119-FW6-4in): Guided Creation
    fills the report's client and location from it.
    """
    code = models.CharField(max_length=6, unique=True, help_text='As job folder names start, e.g. FHR.')
    client = models.CharField(max_length=200, help_text="The report's Client, e.g. Flint Hills Resources.")
    location = models.CharField(max_length=200, blank=True, help_text="The report's Location; blank keeps the defaults'.")

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} · {self.client}'

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)


class WorkingFolder(models.Model):
    """
    A parent working directory: the folder a report type's job folders are kept in (e.g.
    Desktop/Reports/001 Welds for weld reports). Guided Creation lists and makes job folders in
    them; one per report type is the default.
    """
    path = models.CharField(max_length=500, help_text=r'The full path, e.g. C:\Users\…\Desktop\Reports\001 Welds.')
    report_type = models.CharField(max_length=50, help_text='The reports whose job folders are kept here.')
    is_default = models.BooleanField('Default', default=False, help_text="Opened first for this report type.")

    class Meta:
        ordering = ['report_type', '-is_default', 'path']

    def __str__(self):
        return self.path

    @property
    def name(self):
        return os.path.basename(os.path.normpath(self.path)) or self.path

    @property
    def report_type_label(self):
        from .report_types import get_report_type
        return get_report_type(self.report_type).label

    def save(self, *args, **kwargs):
        self.path = self.path.strip().strip('"')
        super().save(*args, **kwargs)
        # One default per report type; the first one for a type is it
        others = WorkingFolder.objects.filter(report_type=self.report_type).exclude(pk=self.pk)
        if self.is_default:
            others.filter(is_default=True).update(is_default=False)
        elif not others.filter(is_default=True).exists():
            WorkingFolder.objects.filter(pk=self.pk).update(is_default=True)
            self.is_default = True
