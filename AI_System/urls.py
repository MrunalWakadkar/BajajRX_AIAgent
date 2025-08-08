from django.contrib import admin
from django.urls import path,include
from . import views

urlpatterns = [
    path('', views.home, name="home"),
    path('upload-document/', views.upload_document, name='upload_document'),
    path('use-existing-document/<int:doc_id>/', views.use_existing_document, name='use_existing_document'),
    path('get-progress/<uuid:task_id>/', views.get_progress, name='get_progress'),
    path('process-query/', views.process_query, name='process_query'),
    path("delete-document/<int:doc_id>/", views.delete_document, name="delete_document"),
    path('embed/', views.generate_embeddings, name='generate_embeddings'),
]
