# psd_app/forms.py
from django import forms
from .models import PSDProcessingJob

class PSDUploadForm(forms.Form):
    psd_file = forms.FileField(
        label='PSD File',
        # help_text='Upload a Photoshop .psd file to process'
    )