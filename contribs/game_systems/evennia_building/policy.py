from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import RegionBuildPolicy

POLICIES = {"open", "residential", "commercial", "closed"}


def primary_region(room):
    if not apps.is_installed("evennia_regions"):
        return None
    from evennia_regions.models import RegionMembership

    membership = RegionMembership.primary_for(room.pk)
    return membership.region if membership and not membership.region.is_archived else None


def resolve_policy(room):
    tags = list(
        room.db_tags.filter(db_category="build_policy", db_tagtype__isnull=True).values_list(
            "db_key", flat=True
        )
    )
    if len(tags) > 1 or any(tag not in POLICIES for tag in tags):
        raise ValidationError("The attachment room has an invalid building policy; ask staff.")
    if tags:
        return tags[0]
    region = primary_region(room)
    if region:
        policy = RegionBuildPolicy.objects.filter(region_id=region.pk).first()
        if policy:
            if policy.policy not in POLICIES:
                raise ValidationError("The region has an invalid building policy; ask staff.")
            return policy.policy
    policy = getattr(settings, "BUILDING_DEFAULT_POLICY", "open")
    if policy not in POLICIES:
        raise ValidationError("The default building policy is invalid; ask staff.")
    return policy


@transaction.atomic
def set_policy(actor, target, policy, *, region=False, reason=""):
    """Staff policy management shared by commands and authenticated pages."""
    from .access import is_staff, require_revealed
    from .services import _text, audit

    require_revealed(actor)
    if not is_staff(actor):
        raise PermissionDenied("Only staff can set building policy.")
    if policy not in POLICIES | {"reset"}:
        raise ValidationError("Choose open, residential, commercial, closed or reset.")
    reason = _text(reason, 10000) if reason else ""
    if region:
        if not apps.is_installed("evennia_regions"):
            raise ValidationError("Region policies are unavailable without Regions.")
        from evennia_regions.models import Region

        target = Region.objects.select_for_update().get(pk=int(target))
        if target.is_archived:
            raise ValidationError("Choose an active region.")
        if policy == "reset":
            RegionBuildPolicy.objects.filter(region_id=target.pk).delete()
        else:
            RegionBuildPolicy.objects.update_or_create(
                region_id=target.pk, defaults={"policy": policy}
            )
    else:
        if not target or not target.is_typeclass(
            "evennia.objects.objects.DefaultRoom", exact=False
        ):
            raise ValidationError("Choose a room.")
        target.tags.clear(category="build_policy")
        if policy != "reset":
            target.tags.add(policy, category="build_policy")
    audit(
        actor,
        "policy_set",
        target=target.pk,
        region=region,
        policy=policy,
        **({"reason": reason} if reason else {}),
    )
