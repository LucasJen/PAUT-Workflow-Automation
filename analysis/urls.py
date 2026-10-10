from django.urls import path

from . import views

urlpatterns = [
    path('', views.analysis, name='analysis'),
    path('files.json', views.files, name='analysis-files'),
    path('file.json', views.file_info, name='analysis-file'),
    path('frame.bin', views.frame, name='analysis-frame'),
    path('readings.json', views.readings, name='analysis-readings'),
    path('projections.json', views.projections_status, name='analysis-projections'),
    path('cscan.bin', views.cscan, name='analysis-cscan'),
    path('bscan.bin', views.bscan, name='analysis-bscan'),
    path('size.json', views.size_indication, name='analysis-size'),
    path('indications.json', views.indications, name='analysis-indications'),
    path('indication/<int:pk>.json', views.indication, name='analysis-indication'),
    path('indications.csv', views.indications_csv, name='analysis-indications-csv'),
    path('reports.json', views.report_targets, name='analysis-report-targets'),
    path('report-preview.json', views.report_preview, name='analysis-report-preview'),
    path('report-send.json', views.report_send, name='analysis-report-send'),
]
