from django.urls import path

from .views import frontiers, properties

app_name = "evennia_building_api"
urlpatterns = [
    path("frontier/", frontiers, name="frontier-list"),
    path("frontier/<int:pk>/", frontiers, name="frontier-detail"),
    path("", properties, name="list"),
    path("<int:pk>/", properties, name="detail"),
]
