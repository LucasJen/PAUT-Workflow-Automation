from django.urls import path

from . import views

urlpatterns = [
    path('', views.assistant, name='assistant'),
    path('chat/<int:pk>/', views.assistant, name='assistant-conversation'),
    path('chat/<int:pk>/delete/', views.delete_conversation, name='assistant-delete'),
    path('ask/', views.ask, name='assistant-ask'),
    path('settings/', views.assistant_settings, name='assistant-settings'),
]
