# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Viewer-aware membership and room detail without requiring maps."""

from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from django.test import RequestFactory, override_settings
from evennia.utils.test_resources import EvenniaTest

from evennia_regions.models import Region, RegionMembership
from evennia_regions.permissions import is_room_web_visible
from evennia_regions.views import RegionDetailView, RoomDetailView


def controlled_preview(room, *, viewer):
    return bool(viewer and room.access(viewer, "control"))


def legacy_preview(room):
    return False


@override_settings(
    ROOT_URLCONF="evennia_regions.tests", REGIONS_ROOM_VISIBILITY=__name__ + ".controlled_preview"
)
class TestViewerVisibility(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.account2.characters.add(self.char2)
        self.room1.locks.add(f"control:id({self.char2.pk})")
        self.room1.key = "Private draft chamber"
        self.region = Region.objects.create(name="Test region")
        RegionMembership.objects.create(
            region=self.region, room=self.room1, room_name=self.room1.key
        )

    def request(self, user):
        request = RequestFactory().get("/regions/")
        request.user = user
        request.session = {}
        return request

    def test_offline_owner_sees_room_and_membership_and_anonymous_does_not(self):
        for user, allowed in ((self.account2, True), (AnonymousUser(), False)):
            request = self.request(user)
            response = RegionDetailView.as_view()(request, pk=self.region.pk)
            response.render()
            self.assertEqual(self.room1.key in response.content.decode(), allowed)
            if allowed:
                response = RoomDetailView.as_view()(request, pk=self.room1.pk)
                response.render()
                self.assertIn(self.room1.key, response.content.decode())
            else:
                with self.assertRaises(Http404):
                    RoomDetailView.as_view()(request, pk=self.room1.pk)

    @override_settings(REGIONS_ROOM_VISIBILITY=__name__ + ".legacy_preview")
    def test_legacy_callback_still_works_with_a_viewer(self):
        self.assertFalse(is_room_web_visible(self.room1, self.char2))
