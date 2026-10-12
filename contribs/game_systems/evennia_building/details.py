"""Visible room provenance, deliberately absent from ordinary look text."""

from .models import FrontierRoom
from .visibility import room_visibility


def room_details(room, viewer=None):
    if room_visibility(room, viewer) is not True:
        return []
    record = (
        FrontierRoom.objects.select_related(
            "frontier__promotion__project", "frontier__promotion__review"
        )
        .filter(room=room, frontier__state="live")
        .first()
    )
    if not record:
        return []
    item = record.frontier
    return [
        ("Reclaimed by", item.promotion.project.owner_name),
        ("Approved by", item.promotion.review.actor_name),
        ("Promoted", item.created_at.isoformat()),
        ("Steward", record.steward_name or "Staff"),
    ]
