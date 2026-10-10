from django.db import models


class Indication(models.Model):
    """
    An indication saved on the Analysis page, like a row of OmniPC's indication table: where it is
    in the file (group, scan line, beam / index line and their positions), the readings and cursors
    at the time, its sizing and a comment. Lengths are in metres, amplitudes in %.
    """
    file_path = models.CharField(max_length=500, db_index=True)
    file_name = models.CharField(max_length=255)
    group = models.IntegerField(default=0)
    number = models.PositiveIntegerField(help_text="Numbered per file, like OmniPC's #.")
    scan = models.IntegerField()
    lateral = models.IntegerField(help_text='Beam or index line.')
    scan_position = models.FloatField(null=True, blank=True)
    index_position = models.FloatField(null=True, blank=True)
    angle = models.FloatField(null=True, blank=True)
    gain = models.FloatField(default=0)
    readings = models.JSONField(default=dict, blank=True)
    cursors = models.JSONField(default=dict, blank=True)
    sizing = models.JSONField(default=dict, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['file_path', 'number']

    def __str__(self):
        return f'{self.file_name} #{self.number}'

    def as_dict(self):
        return {
            'id': self.pk, 'number': self.number, 'group': self.group, 'scan': self.scan, 'lateral': self.lateral,
            'scan_position': self.scan_position, 'index_position': self.index_position, 'angle': self.angle,
            'gain': self.gain, 'readings': self.readings, 'cursors': self.cursors, 'sizing': self.sizing,
            'comment': self.comment, 'created_at': self.created_at.isoformat() if self.created_at else None,
        }
