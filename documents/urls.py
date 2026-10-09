from django.urls import path

from . import views
from .models import Document

urlpatterns = [
    path('<int:pk>/open/', views.open_document, name='open-document'),
    path('revision/<int:pk>/open/', views.open_revision, name='open-revision'),
    path('search/', views.document_search, name='document-search'),

    path('procedures/', views.document_list, {'category': Document.PROCEDURE}, name='procedure-list'),
    path('procedure/<int:pk>/edit/', views.edit_document, {'category': Document.PROCEDURE},
         name='edit-procedure'),

    path('code-material/', views.document_list, {'category': Document.CODE}, name='code-material-list'),
    path('code-material/<int:pk>/edit/', views.edit_document, {'category': Document.CODE},
         name='edit-code-material'),

    path('training-material/', views.document_list, {'category': Document.TRAINING},
         name='training-material-list'),
    path('training-material/<int:pk>/edit/', views.edit_document, {'category': Document.TRAINING},
         name='edit-training-material'),

    path('report-forms/', views.document_list, {'category': Document.FORM}, name='report-form-list'),
    path('report-form/<int:pk>/edit/', views.edit_document, {'category': Document.FORM},
         name='edit-report-form'),
]
