from django.urls import path

from . import views

urlpatterns = [
    path('', views.analysis, name='analysis'),
    path('files.json', views.files, name='analysis-files'),
    path('file.json', views.file_info, name='analysis-file'),
    path('frame.bin', views.frame, name='analysis-frame'),
    path('readings.json', views.readings, name='analysis-readings'),
]
