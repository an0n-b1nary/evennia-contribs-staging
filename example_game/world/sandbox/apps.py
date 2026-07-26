"""AppConfig for world.sandbox — the game's contrib-glue app.

world.sandbox is already in INSTALLED_APPS (for the seed_sandbox management
command and the dotted-path glue hooks in glue.py). ready() additionally
connects evennia_posing's pose_recorded signal to the single ordered
listener in glue.py. Modern Django auto-discovers a single AppConfig
subclass in apps.py, so no settings change is needed for this config.
"""

from django.apps import AppConfig


class SandboxConfig(AppConfig):
    """Wires the pose_recorded signal to the sandbox glue listener."""

    name = "world.sandbox"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from evennia_posing.signals import pose_recorded
        from world.sandbox import glue

        pose_recorded.connect(
            glue.on_pose_recorded,
            dispatch_uid="world.sandbox.on_pose_recorded",
        )
