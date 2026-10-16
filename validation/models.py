from django.db import models

from .kit import DEFAULT_PATH


class ValidationSettings(models.Model):
    """The one row of settings: where the validation kit is."""
    kit_path = models.CharField(max_length=500, default=DEFAULT_PATH)

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]


class ValidationRun(models.Model):
    """
    One validation run, kept as evidence: when, which version of the app (git commit), which kit (its
    path and the manifest's fingerprint), the layers run and every check's result (results JSON, filled
    in as the run goes). A finished run doesn't change; its report is made from it.
    """
    RUNNING, PASSED, FAILED, ERROR, CANCELLED = 'running', 'passed', 'failed', 'error', 'cancelled'
    STATUS_CHOICES = [(RUNNING, 'Running'), (PASSED, 'Passed'), (FAILED, 'Failed'), (ERROR, 'Error'), (CANCELLED, 'Cancelled')]
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=RUNNING)
    layers = models.JSONField(default=list)
    options = models.JSONField(default=dict, blank=True)
    kit_path = models.CharField(max_length=500)
    manifest_sha = models.CharField(max_length=64, blank=True)
    version = models.CharField(max_length=80, blank=True, help_text='The git commit the app ran at (+ "modified").')
    computer = models.CharField(max_length=120, blank=True)
    passed = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    results = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Validation run {self.pk} ({self.status})'
