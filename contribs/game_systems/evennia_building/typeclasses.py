class BuildingRoomMixin:
    """Place before DefaultRoom; room deletion is a lifecycle service."""

    def at_object_delete(self):
        from .access import ownership
        from .models import DraftRoom

        if not self.ndb.building_cleanup and (
            ownership(self) or DraftRoom.objects.filter(object_id=self.pk).exists()
        ):
            return False
        return super().at_object_delete()

    def at_object_receive(self, moved_obj, source_location, **kwargs):
        result = super().at_object_receive(moved_obj, source_location, **kwargs)
        from .access import is_staff, ownership
        from .services import audit

        record = ownership(self)
        if record and moved_obj.pk != record.owner_id and is_staff(moved_obj):
            audit(
                moved_obj,
                "staff_entry",
                property=record.property,
                room=self.pk,
                source=getattr(source_location, "pk", None),
            )
        return result


class BuildingCharacterMixin:
    """Place before DefaultCharacter; cooperative puppet hooks record own play."""

    def at_post_puppet(self, **kwargs):
        from django.utils import timezone

        result = super().at_post_puppet(**kwargs)
        self.attributes.add("building_last_played", timezone.now())
        return result

    def at_post_unpuppet(self, account=None, session=None, **kwargs):
        from django.utils import timezone

        result = super().at_post_unpuppet(account=account, session=session, **kwargs)
        self.attributes.add("building_last_played", timezone.now())
        return result


class BuildingExitMixin:
    """Place before DefaultExit. Departure exits retain unrestricted traversal."""

    def at_object_delete(self):
        from .attachments import protected_exit
        from .models import DraftDoor, Property

        if (
            protected_exit(self)
            or Property.objects.filter(entrance=self).exists()
            or Property.objects.filter(departure=self).exists()
        ):
            return False
        if (
            not self.ndb.building_cleanup
            and DraftDoor.objects.filter(
                exit=self, project__state__in=["draft", "submitted", "promoted"]
            ).exists()
        ):
            return False
        return super().at_object_delete()

    def at_traverse(self, traversing_object, target_location, **kwargs):
        from .access import can_enter
        from .attachments import departure_allows
        from .models import DraftDoor, Property

        outward = (
            DraftDoor.objects.filter(exit=self, outward=True).exists()
            or Property.objects.filter(departure=self).exists()
        )
        if (
            not outward
            and not departure_allows(self)
            and not can_enter(traversing_object, target_location)
        ):
            traversing_object.msg("You do not have permission to enter.")
            return
        return super().at_traverse(traversing_object, target_location, **kwargs)
