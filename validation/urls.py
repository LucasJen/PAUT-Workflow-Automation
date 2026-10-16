from django.urls import path

from . import views

urlpatterns = [
    path('', views.validation, name='validation'),
    path('run.json', views.run_start, name='validation-run-start'),
    path('run/<int:pk>.json', views.run_status, name='validation-run'),
    path('run/<int:pk>/cancel.json', views.run_cancel, name='validation-run-cancel'),
    path('run/<int:pk>/picture/<str:name>', views.run_picture, name='validation-run-picture'),
    path('run/<int:pk>/report.docx', views.run_report, name='validation-run-report'),
]
