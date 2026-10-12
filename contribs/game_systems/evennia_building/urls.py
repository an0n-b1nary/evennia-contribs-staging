from django.urls import path

from . import views

app_name = "evennia_building"
urlpatterns = [
    path("", views.index, name="index"),
    path("projects/<int:pk>/", views.project_detail, name="project"),
    path("submissions/<int:pk>/", views.submission_detail, name="submission"),
    path("properties/<int:pk>/", views.property_detail, name="property"),
    path("invitations/<int:pk>/answer/", views.invitation_answer, name="invitation-answer"),
    path("consents/<int:pk>/", views.consent_detail, name="consent"),
    path("passage/<int:pk>/", views.passage_detail, name="passage"),
]
