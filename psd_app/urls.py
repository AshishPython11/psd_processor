from django.urls import path
from .views import upload_psd  # Make sure this import exists

urlpatterns = [
    path('', upload_psd, name='psd_upload'),  # This defines the URL name
]