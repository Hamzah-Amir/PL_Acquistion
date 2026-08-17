from django.urls import path

from . import views

app_name = "builder"

urlpatterns = [
    path("", views.upload, name="upload"),
    path("job/<uuid:job_id>/processing/", views.processing, name="processing"),
    path("job/<uuid:job_id>/progress/", views.progress, name="progress"),
    path("job/<uuid:job_id>/review/", views.review, name="review"),
    path("job/<uuid:job_id>/costs/", views.costs, name="costs"),
    path("job/<uuid:job_id>/assumptions/", views.assumptions, name="assumptions"),
    path("job/<uuid:job_id>/result/", views.result, name="result"),
    path("job/<uuid:job_id>/download/", views.download, name="download"),
    path("job/<uuid:job_id>/discard/", views.discard, name="discard"),
]
