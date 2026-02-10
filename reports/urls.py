from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('create/hic/', views.create_hic_report, name='create_hic_report'),
]