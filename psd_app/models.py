
from django.db import models
from django.core.validators import FileExtensionValidator

class PSDProcessingJob(models.Model):

    psd_file = models.FileField(upload_to='psd_files/', validators=[FileExtensionValidator(['psd'])])
    