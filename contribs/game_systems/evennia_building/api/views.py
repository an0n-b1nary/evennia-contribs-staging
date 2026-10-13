from django.shortcuts import get_object_or_404
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from evennia_building.models import Frontier, Property
from evennia_building.views import actor_for, property_rooms


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def frontiers(request, pk=None):
    actor_for(request)
    queryset = Frontier.objects.filter(state="live").prefetch_related("rooms__room")
    if pk is not None:
        queryset = [get_object_or_404(queryset, pk=pk)]
    result = [
        {
            "id": item.pk,
            "name": item.name,
            "promoted_at": item.created_at.isoformat(),
            "reclaimed_by": item.provenance.get("reclaimed_by"),
            "approved_by": item.provenance.get("actor"),
            "rooms": [
                {
                    "id": row.object_id,
                    "name": row.room.key,
                    "description": row.room.db.desc or "",
                    "steward": row.steward_name,
                }
                for row in item.rooms.all()
                if row.room_id
            ],
        }
        for item in queryset
    ]
    return Response(result[0] if pk is not None else result)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def properties(request, pk=None):
    actor = actor_for(request)
    queryset = Property.objects.filter(state="live")
    if pk is not None:
        queryset = [get_object_or_404(queryset, pk=pk)]
    result = []
    for property in queryset:
        rooms = property_rooms(property, actor)
        if rooms:
            result.append(
                {
                    "id": property.pk,
                    "name": property.name,
                    "owner": property.owner_name,
                    "locked": property.locked,
                    "rooms": [
                        {"id": room.pk, "name": room.key, "description": room.db.desc or ""}
                        for room in rooms
                    ],
                }
            )
    if pk is not None:
        if not result:
            from rest_framework.exceptions import NotFound

            raise NotFound()
        return Response(result[0])
    return Response(result)
