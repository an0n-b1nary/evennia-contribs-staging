"""
Exits

Exits are connectors between Rooms. An exit always has a destination property
set and has a single command defined on itself with the same name as its key,
for allowing Characters to traverse the exit to its destination.

"""

from django.apps import apps
from evennia.objects.objects import DefaultExit

from .objects import ObjectParent

if apps.is_installed("evennia_building"):
    from evennia_building.typeclasses import BuildingExitMixin
else:

    class BuildingExitMixin:
        pass


class Exit(BuildingExitMixin, ObjectParent, DefaultExit):
    """
    Exits are connectors between rooms. Exits are normal Objects except
    they defines the `destination` property and overrides some hooks
    and methods to represent the exits.

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Objects child classes like this.

    """

    pass
