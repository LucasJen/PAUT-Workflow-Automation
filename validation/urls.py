from django.urls import path

from . import views

urlpatterns = [
    path('', views.validation, name='validation'),
    path('run.json', views.run_start, name='validation-run-start'),
    path('run/<int:pk>.json', views.run_status, name='validation-run'),
    path('run/<int:pk>/cancel.json', views.run_cancel, name='validation-run-cancel'),
]
