from django.urls import path
from . import views

urlpatterns = [
    # path('', views.home, name='home'),
    path('presets/', views.presets, name='presets'),
    path('create/', views.create_report, name='create-report'),
    path('report list/', views.report_list, name='report-list')
]
