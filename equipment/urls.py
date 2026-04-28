from django.urls import path
from . import views

urlpatterns = [
    path('scopes/', views.scope_list, name='scope-list'),
    path('scopes/new/', views.new_scope, name='new-scope'),
    path('scope/<int:pk>/edit/', views.edit_scope, name='edit-scope'),

    path('probes/', views.probe_list, name='probe-list'),
    path('probes/new/', views.new_probe, name='new-probe'),
    path('probe/<int:pk>/edit/', views.edit_probe, name='edit-probe'),

    path('calibration-blocks/', views.cal_block_list, name='cal-block-list'),
    path('calibration-blocks/new/', views.new_cal_block, name='new-cal-block'),
    path('calibration-block/<int:pk>/edit/', views.edit_cal_block, name='edit-cal-block'),

    path('sensitivity-blocks/', views.sensitivity_block_list, name='sensitivity-block-list'),
    path('sensitivity-blocks/new/', views.new_sensitivity_block, name='new-sensitivity-block'),
    path('sensitivity-block/<int:pk>/edit/', views.edit_sensitivity_block, name='edit-sensitivity-block'),

    path('encoders/', views.encoder_list, name='encoder-list'),
    path('encoders/new/', views.new_encoder, name='new-encoder'),
    path('encoder/<int:pk>/edit/', views.edit_encoder, name='edit-encoder'),
]
