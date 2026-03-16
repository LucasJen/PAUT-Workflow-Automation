from django.db import models

class Report(models.Model):
    """
    The reports model is used to store user input data with specific job information.
    """
    # Project File Name
    document_filename = models.CharField(max_length=200)

    # Project Information
    document_title = models.CharField(max_length=200)
    client = models.CharField(max_length=200)
    location = models.CharField(max_length=200)
    work_order = models.CharField(max_length=100)
    project_number = models.CharField(max_length=100)
    report_date = models.DateField()
    test_date = models.DateField()
    project_type = models.CharField(max_length=200)
    procedure = models.CharField(max_length=200)

    # Technician Information
    technician_name = models.CharField(max_length=200)
    certification = models.CharField(max_length=200)
    assistant_name = models.CharField(max_length=200, blank=True)
    assistant_certification = models.CharField(max_length=200, blank=True)

    # Executive Summary
    examination_scope = models.TextField()
    executive_summary = models.TextField()

    # Job Scope, References and Method
    equipment_id = models.CharField(max_length=200)
    equipment_overview = models.TextField()
    work_scope = models.TextField()
    x_axis_reference = models.CharField(max_length=200)
    y_axis_reference = models.CharField(max_length=200)
    ut_method = models.CharField(max_length=200)

    def __str__(self):
        return f"{self.document_title} - {self.client}"


class Setup(models.Model):
    """
    The setup model will store equipment specific information to be recalled as needed.
    """
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='setups')

    #UT Equipment Information
    manufacturer = models.CharField(max_length=200, blank=True)
    scope_model = models.CharField(max_length=200, blank=True)
    scope_serial = models.CharField(max_length=200, blank=True)
    transducer_model = models.CharField(max_length=200, blank=True)
    transducer_serial = models.CharField(max_length=200, blank=True)

    #UT Setup Information
    foc_depth = models.CharField(max_length=100, blank=True)
    wave_propogation = models.CharField(max_length=100, blank=True)
    freq = models.CharField(max_length=100, blank=True)
    elements = models.CharField(max_length=100, blank=True)
    x_res = models.CharField(max_length=100, blank=True)
    y_res = models.CharField(max_length=100, blank=True)

    #Calibration information
    cal_material = models.CharField(max_length=200, blank=True)
    material_temp = models.CharField(max_length=50, blank=True)
    cal_block_type = models.CharField(max_length=200, blank=True)
    cal_block_serial = models.CharField(max_length=200, blank=True)
    surface_prep = models.CharField(max_length=200, blank=True)
    tr_min = models.CharField(max_length=50, blank=True)
    tr_max = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"Setup {self.pk} - {self.report}"