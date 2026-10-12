from django.urls import path

from .views import properties

app_name = "evennia_building_api"
urlpatterns = [path("", properties, name="list"), path("<int:pk>/", properties, name="detail")]
