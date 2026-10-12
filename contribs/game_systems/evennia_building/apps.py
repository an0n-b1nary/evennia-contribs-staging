from django.apps import AppConfig, apps


class BuildingConfig(AppConfig):
    name = "evennia_building"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from .runtime import register

        register()
        if apps.is_installed("evennia_regions"):
            from evennia_links import connect_soft_ref_cleanup

            from .models import RegionBuildPolicy

            connect_soft_ref_cleanup(
                apps.get_model("evennia_regions", "Region"), RegionBuildPolicy, "region_id"
            )
        if apps.is_installed("evennia_jobs"):
            from . import jobs

            jobs.connect()
