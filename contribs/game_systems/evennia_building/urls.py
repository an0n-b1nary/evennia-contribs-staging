from django.urls import path

from . import frontier_views, views

app_name = "evennia_building"
urlpatterns = [
    path("", views.index, name="index"),
    path("projects/<int:pk>/", views.project_detail, name="project"),
    path(
        "projects/<int:pk>/collaboration/",
        frontier_views.collaboration_detail,
        name="collaboration",
    ),
    path(
        "collaboration/<int:pk>/answer/",
        frontier_views.collaboration_answer,
        name="collaboration-answer",
    ),
    path("frontier/", frontier_views.frontier_index, name="frontier-list"),
    path("frontier/<int:pk>/", frontier_views.frontier_detail, name="frontier"),
    path("submissions/<int:pk>/", views.submission_detail, name="submission"),
    path("properties/<int:pk>/", views.property_detail, name="property"),
    path("invitations/<int:pk>/answer/", views.invitation_answer, name="invitation-answer"),
    path("consents/<int:pk>/", views.consent_detail, name="consent"),
    path("passage/<int:pk>/", views.passage_detail, name="passage"),
]
