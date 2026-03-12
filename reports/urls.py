from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('create/', views.create_report, name='create-report'),
    path('setups/', views.setup_list, name='setup-list'),
    path('setup/<int:pk>/edit/', views.edit_setups, name='edit-setups'),
    path('report list/', views.report_list, name='report-list')
]
