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


class Probe(models.Model):
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
    serial_number = models.CharField(max_length=200, blank=True)
    material = models.CharField(max_length=200, blank=True)
    block_type = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.block_type} - {self.serial_number}"


class Encoder(models.Model):
    manufacturer = models.CharField(max_length=200, blank=True)
    model = models.CharField(max_length=200, blank=True)
    serial_number = models.CharField(max_length=200, blank=True)
    encoder_type = models.CharField(max_length=200, blank=True)
    step_count = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.model} ({self.serial_number})"
