from django.db import models

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
    notes = models.TextField(blank=True)
    scan_plan = models.ForeignKey('ScanPlan', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports')

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

    def __str__(self):
        return f"{self.pk} | {self.document_filename}"

    @property
    def prepared_by_names(self):
        return ', '.join(p.name for p in self.people.all() if p.prepared)


class ScanPlan(models.Model):
    """
    Scan plan for a basic single-V butt weld, drawn by reports/services/scan_plan.py and printed
    on the weld report's Scan Plan page. Saved on its own so one plan serves every report for the
    same pipe size and setup. Lengths are in inches, angles in degrees.
    """
    ONE_LEG, TWO_LEGS = 1, 2
    LEG_CHOICES = [(ONE_LEG, 'First leg only'), (TWO_LEGS, 'First and second leg')]
    SKEW_90, SKEW_270 = 90, 270

    name = models.CharField(max_length=100)
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
    KIND_CHOICES = [
        (SCAN, 'Scan image (photo summary)'),
        (DRAWING, 'Equipment drawing'),
    ]

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='images')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=SCAN)
    image = models.ImageField(upload_to='report_images/')
    # Drawings: the drawing's title. Scan images: optional label when not tied to a results row.
    caption = models.CharField(max_length=200, blank=True)
    # Scan images: the results-table Scan ID this image belongs to (matched by text, because
    # results rows are recreated on every save); its comments come from that row.
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