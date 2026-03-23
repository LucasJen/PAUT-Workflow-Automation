from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('create/', views.create_report, name='create-report'),
    path('setups/', views.setup_list, name='setup-list'),
    path('setups/new/', views.new_setup, name='new-setup'),
    path('setup/<int:pk>/edit/', views.edit_setup, name='edit-setup'),
    path('reports/', views.report_list, name='report-list'),
    path('reports/new/', views.new_report, name='new-report'),
    path('report/<int:pk>/generate/', views.generate_report, name='generate-report'),
    path('reports/<int:pk>/edit/', views.edit_existing_report, name='edit-report'),
    path('nde/', views.nde_upload, name='nde-upload'),
]
