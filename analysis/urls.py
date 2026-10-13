from django.urls import path

from . import views

urlpatterns = [
    path('', views.analysis, name='analysis'),
    path('files.json', views.files, name='analysis-files'),
    path('file.json', views.file_info, name='analysis-file'),
    path('frame.bin', views.frame, name='analysis-frame'),
    path('readings.json', views.readings, name='analysis-readings'),
    path('frame-gates.json', views.frame_gates, name='analysis-frame-gates'),
    path('projections.json', views.projections_status, name='analysis-projections'),
    path('cscan.bin', views.cscan, name='analysis-cscan'),
    path('bscan.bin', views.bscan, name='analysis-bscan'),
    path('size.json', views.size_indication, name='analysis-size'),
    path('detect.json', views.detect_indications, name='analysis-detect'),
    path('indication/<int:pk>/resize.json', views.resize_indication, name='analysis-resize'),
    path('indications.json', views.indications, name='analysis-indications'),
    path('indication/<int:pk>.json', views.indication, name='analysis-indication'),
    path('indications/clear.json', views.clear_indications, name='analysis-clear-indications'),
    path('indications.csv', views.indications_csv, name='analysis-indications-csv'),
    path('browse.json', views.browse_pc, name='analysis-browse'),
    path('open-file.json', views.open_external, name='analysis-open-file'),
    path('forget-file.json', views.forget_external, name='analysis-forget-file'),
    path('project-options.json', views.project_options, name='analysis-project-options'),
    path('project.json', views.project_start, name='analysis-project'),
    path('project-status.json', views.project_status, name='analysis-project-status'),
    path('weld-outline.json', views.weld_outline, name='analysis-weld-outline'),
    path('reports.json', views.report_targets, name='analysis-report-targets'),
    path('report-preview.json', views.report_preview, name='analysis-report-preview'),
    path('report-send.json', views.report_send, name='analysis-report-send'),
]
