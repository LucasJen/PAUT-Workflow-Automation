from django.db import models

class Report(models.Model):
    """
    The reports model is used to store user input data with specific job information.
    """
    # Project File Name
    document_filename = models.CharField(max_length=200, blank=True)

    # Project Information
    document_title = models.TextField(blank=True)
    client = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    work_order = models.CharField(max_length=100, blank=True)
    project_number = models.CharField(max_length=100, blank=True)
    report_date = models.DateField(blank=True, null=True)
    test_date = models.DateField(blank=True, null=True)
    project_type = models.CharField(max_length=200, blank=True)
    procedure = models.CharField(max_length=200, blank=True)

    # Technician Information
    technician_name = models.CharField(max_length=200, blank=True)
    certification = models.CharField(max_length=200, blank=True)
    assistant_name = models.CharField(max_length=200, blank=True)
    assistant_certification = models.CharField(max_length=200, blank=True)

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


class Setup(models.Model):
    """
    The setup model will store equipment specific information to be recalled as needed.
    """
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='setups', null=True, blank=True)

    # UT Equipment Information
    manufacturer = models.CharField(max_length=200, blank=True, default="Evident")
    scope_model = models.CharField(max_length=200, blank=True)
    scope_serial = models.CharField(max_length=200, blank=True)
    transducer_model = models.CharField(max_length=200, blank=True)
    transducer_serial = models.CharField(max_length=200, blank=True)

    # UT Setup Information
    foc_depth = models.CharField(max_length=100, blank=True)
    wave_propagation = models.CharField(max_length=100, blank=True)
    freq = models.CharField(max_length=100, blank=True)
    elements = models.CharField(max_length=100, blank=True)
    x_res = models.CharField(max_length=100, blank=True, default=0.039)
    y_res = models.CharField(max_length=100, blank=True, default=0.039)

    # Calibration information
    cal_material = models.CharField(max_length=200, blank=True)
    material_temp = models.CharField(max_length=50, blank=True)
    cal_block_type = models.CharField(max_length=200, blank=True)
    cal_block_serial = models.CharField(max_length=200, blank=True)
    surface_prep = models.CharField(max_length=200, blank=True)
    tr_min = models.CharField(max_length=50, blank=True)
    tr_max = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"Setup {self.pk} - {self.report}"