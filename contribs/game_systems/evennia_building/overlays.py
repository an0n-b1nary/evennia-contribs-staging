"""One bulk query for public growth metadata; drafts and interiors never appear."""

from evennia_links.runtime import get

from .models import FrontierRoom


def provide(sender, room_ids, *, staff=False, viewer=None, **kwargs):
    if not staff and not get("BUILDING_REVEALED"):
        return {}
    return {
        "frontier": {
            row.object_id: {
                "id": row.frontier_id,
                "name": row.frontier.name,
                "promoted_at": row.frontier.created_at.isoformat(),
                "reclaimed_by": row.frontier.provenance.get("reclaimed_by"),
                "approved_by": row.frontier.provenance.get("actor"),
                "steward": row.steward_name,
            }
            for row in FrontierRoom.objects.filter(
                object_id__in=room_ids, room__isnull=False, frontier__state="live"
            ).select_related("frontier")
        }
    }
