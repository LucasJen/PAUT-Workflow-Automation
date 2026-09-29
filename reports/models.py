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

    # Heading of the optional data-comparison figure section
    comparison_title = models.CharField(max_length=200, blank=True, default='DATA COMPARISON')

    # Executive Summary
    examination_scope = models.TextField(blank=True)
    executive_summary = models.TextField(blank=True)
    
    # Job Scope, References and Method
    equipment_id = models.CharField(max_length=200, blank=True)
    equipment_overview = models.TextField(blank=True)
    work_scope = models.TextField(blank=True)
    x_axis_reference = models.CharField(max_length=200, blank=True)
    y_axis_reference = models.CharField(max_length=200, blank=True)
    ut_method = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"{self.pk} | {self.document_filename}"

    @property
    def prepared_by_names(self):
        return ', '.join(p.name for p in self.people.all() if p.prepared)


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
    COMPARISON = 'comparison'
    KIND_CHOICES = [
        (SCAN, 'Scan image (photo summary)'),
        (DRAWING, 'Equipment drawing'),
        (COMPARISON, 'Data comparison'),
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