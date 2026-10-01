from django.db import models


class Scope(models.Model):
    manufacturer = models.CharField(max_length=200, blank=True, default='Evident')
    software = models.CharField(max_length=200, blank=True, default='OmniPC')
    software_version = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=200, blank=True)
    serial_number = models.CharField(max_length=200, blank=True)
    calibration_date = models.DateField(blank=True, null=True)
    calibration_due_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.model} ({self.serial_number})"


class ProbeModel(models.Model):
    """
    Probe catalogue: one entry per probe model with the manufacturer's specifications.
    Lengths in mm. Serial-numbered probes (Probe) point to their model here.
    """
    model = models.CharField(max_length=100, unique=True)
    series = models.CharField(max_length=50, blank=True, help_text='Housing / series, e.g. A1, A32.')
    manufacturer = models.CharField(max_length=100, blank=True, default='Evident')
    item_number = models.CharField(max_length=50, blank=True)
    frequency = models.FloatField(null=True, blank=True, help_text='MHz')
    elements = models.PositiveIntegerField(null=True, blank=True)
    pitch = models.FloatField(null=True, blank=True, help_text='Element pitch, mm')
    aperture = models.FloatField(null=True, blank=True, help_text='Active aperture, mm')
    elevation = models.FloatField(null=True, blank=True, help_text='Element width (elevation), mm')
    length = models.FloatField(null=True, blank=True, help_text='Housing length, mm')
    width = models.FloatField(null=True, blank=True, help_text='Housing width, mm')
    height = models.FloatField(null=True, blank=True, help_text='Housing height, mm')
    source = models.CharField(max_length=300, blank=True, help_text='Datasheet or catalogue the specs come from.')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['series', 'frequency', 'elements', 'model']

    def __str__(self):
        return self.model


class WedgeModel(models.Model):
    """
    Wedge catalogue. The catalogue gives the angle and size; the geometry the scan plan needs
    (wedge angle, velocity, first element height, primary offset) comes from an OmniScan .nde
    file or a beam-modelling tool. Lengths in mm, velocity in m/s.
    """
    SHEAR, LONGITUDINAL = 'SW', 'LW'
    WAVE_CHOICES = [(SHEAR, 'Shear'), (LONGITUDINAL, 'Longitudinal')]

    model = models.CharField(max_length=100, unique=True)
    probe_series = models.CharField(max_length=50, blank=True, help_text='Probe series it fits, e.g. A1.')
    manufacturer = models.CharField(max_length=100, blank=True, default='Evident')
    refracted_angle = models.FloatField(null=True, blank=True, help_text='Nominal refracted angle in steel, °')
    wave_type = models.CharField(max_length=2, choices=WAVE_CHOICES, blank=True)
    sweep = models.CharField(max_length=50, blank=True, help_text='Recommended sweep, e.g. 40 to 70°')
    length = models.FloatField(null=True, blank=True, help_text='mm')
    width = models.FloatField(null=True, blank=True, help_text='mm')
    width_wings = models.FloatField(null=True, blank=True, help_text='Width with scanner wings, mm')
    height = models.FloatField(null=True, blank=True, help_text='mm')
    # Geometry for the beam exit point
    wedge_angle = models.FloatField(null=True, blank=True, help_text='Probe face angle, °')
    velocity = models.FloatField(null=True, blank=True, help_text='Wedge material velocity, m/s')
    first_element_height = models.FloatField(null=True, blank=True, help_text='Height to the first element centre, mm')
    primary_offset = models.FloatField(
        null=True, blank=True,
        help_text='Wedge front to the first element centre along the scan axis, mm '
                  '(negative = behind the front face, as OmniScan shows it).')
    secondary_offset = models.FloatField(null=True, blank=True, help_text='Wedge side to the element centre, mm')
    roof_angle = models.FloatField(null=True, blank=True, help_text='°')
    bottom_face = models.CharField(max_length=20, blank=True, help_text='Flat, AOD, COD, AID, …')
    part_diameter = models.FloatField(null=True, blank=True, help_text='Diameter the curved face fits, mm')
    probe_fit = models.CharField(max_length=100, blank=True,
                                 help_text='Probe this geometry is for, e.g. 10L32 or 5/10L32 (from the library name).')
    source = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['probe_series', 'model']

    def __str__(self):
        return self.model

    @property
    def has_geometry(self):
        return None not in (self.wedge_angle, self.velocity, self.first_element_height, self.primary_offset)


class Probe(models.Model):
    """A serial-numbered probe in the inventory; its specifications come from its catalogue model."""
    catalogue = models.ForeignKey(ProbeModel, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='probes', verbose_name='Catalogue model')
    manufacturer = models.CharField(max_length=200, blank=True)
    model = models.CharField(max_length=200, blank=True)
    serial_number = models.CharField(max_length=200, blank=True)
    frequency = models.CharField(max_length=100, blank=True)
    elements = models.CharField(max_length=100, blank=True)
    diameter = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.model} ({self.serial_number})"


class CalibrationBlock(models.Model):
    serial_number = models.CharField(max_length=200, blank=True)
    material = models.CharField(max_length=200, blank=True)
    block_type = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.block_type} - {self.serial_number}"


class SensitivityBlock(models.Model):
    """
    Sensitivity block table (the weld form's Cal Block Table): one row per pipe size with its
    calibration standard and the defaults for the item inspected. Picking one on a scan plan
    fills the scan plan and the weld report's Material Information.
    """
    pipe_size = models.CharField('NPS / Sch', max_length=100, blank=True, help_text='e.g. 6in Sch 40')
    serial_number = models.CharField('Cal Std. #', max_length=200, blank=True)
    block_type = models.CharField(max_length=200, blank=True, help_text='e.g. Notch, SDH')
    material = models.CharField(max_length=200, blank=True)
    velocity_shear = models.CharField('Shear velocity', max_length=50, blank=True, help_text='e.g. 0.128 in/µs')
    velocity_long = models.CharField('L-wave velocity', max_length=50, blank=True)
    cal_diameter = models.CharField('Cal. diameter', max_length=50, blank=True)
    cal_sch_nom = models.CharField('Cal. Sch / nom. thk', max_length=100, blank=True)
    cal_thickness = models.CharField('Cal. thickness', max_length=50, blank=True)
    temperature = models.CharField('Temp (°F)', max_length=50, blank=True)
    surface_cal = models.CharField('Surface (cal.)', max_length=100, blank=True)
    surface_test = models.CharField('Surface (test)', max_length=100, blank=True)
    couplant = models.CharField(max_length=100, blank=True)
    bevel_geometry = models.CharField(max_length=100, blank=True, help_text='e.g. 37 degrees')
    encoder = models.CharField(max_length=100, blank=True)
    encoder_steps = models.CharField(max_length=100, blank=True)
    scan_res = models.CharField('Scan res.', max_length=50, blank=True)
    scan_speed = models.CharField(max_length=50, blank=True)
    test_diameter = models.CharField('Test diameter', max_length=50, blank=True)
    test_thickness = models.CharField('Test thickness', max_length=50, blank=True)
    test_sch_nom = models.CharField('Test Sch / nom. thk', max_length=100, blank=True)
    reflector_depth = models.CharField('Notch / SDH depth', max_length=50, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['pk']

    def __str__(self):
        return self.pipe_size or f"{self.block_type} - {self.serial_number}"


class Encoder(models.Model):
    manufacturer = models.CharField(max_length=200, blank=True)
    model = models.CharField(max_length=200, blank=True)
    serial_number = models.CharField(max_length=200, blank=True)
    encoder_type = models.CharField(max_length=200, blank=True)
    step_count = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.model} ({self.serial_number})"
