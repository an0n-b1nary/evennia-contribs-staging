# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Tests for evennia_regions.

Covers:
- Region model CRUD, soft-archive, create_region factory, signal fire
- RegionMembership many-to-many membership, the one-primary-per-room
  partial unique constraint, and primary_for() resolution/fallback
- CmdRegion switches end-to-end (bare list, /view, /here, /create,
  /add-room, /remove-room, /here-add, /primary, permission gates)
- RegionListView and RegionDetailView web responses, both as context and
  fully rendered

Uses:
    EvenniaTest            — base for model tests (provides char1/char2/room1)
    EvenniaCommandTest      — base for command tests (.call())

This module doubles as a **test URLconf** (see ``urlpatterns`` below). Cases
that reverse a URL or render a template opt in with
``@override_settings(ROOT_URLCONF=__name__)``.

Run:
    evennia test evennia_regions --settings settings.py
"""

import unittest
from importlib import import_module
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import RequestFactory, override_settings
from django.urls import include, path
from evennia.utils.test_resources import EvenniaCommandTest, EvenniaTest
from evennia.web.urls import urlpatterns as evennia_default_urlpatterns

from evennia_regions.commands import CmdRegion
from evennia_regions.integrations import maps as maps_overlays
from evennia_regions.models import Region, RegionMembership
from evennia_regions.permissions import is_room_web_visible
from evennia_regions.views import RegionDetailView, RegionListView

# ---------------------------------------------------------------------------
# Test URLconf (see the module docstring)
# ---------------------------------------------------------------------------

# The region templates reverse their own routes through the evennia_regions
# namespace, so they are mounted namespaced exactly as urls.py documents.
# Evennia's own routes come along because website/base.html — which both
# region templates extend — reverses "index" and the account routes.
urlpatterns = [
    path("regions/", include(("evennia_regions.urls", "evennia_regions"))),
    *evennia_default_urlpatterns,
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_region(name="The Grasslands", creator=None, description="Wide open fields."):
    return Region.create_region(name=name, creator=creator, description=description)


def _always_hidden(room):
    """REGIONS_ROOM_VISIBILITY test stub: every room is hidden."""
    return False


def _always_visible(room):
    """REGIONS_ROOM_VISIBILITY test stub: every room is visible."""
    return True


def _exploding_rule(room):
    """REGIONS_ROOM_VISIBILITY test stub: raises when called."""
    raise RuntimeError("visibility rule blew up")


_NOT_CALLABLE = None
"""REGIONS_ROOM_VISIBILITY test stub: a dotted path that resolves to None."""


# ---------------------------------------------------------------------------
# Region model tests
# ---------------------------------------------------------------------------


class TestRegionModel(EvenniaTest):
    """Region CRUD, __str__, member_count, archive/unarchive."""

    def test_create_region_sets_fields(self):
        r = _make_region("The Ashfields", creator=self.char1, description="Volcanic.")
        self.assertEqual(r.name, "The Ashfields")
        self.assertEqual(r.description, "Volcanic.")
        self.assertEqual(r.created_by, self.char1)
        self.assertEqual(r.created_by_name, self.char1.key)

    def test_create_region_no_creator(self):
        r = _make_region("The Void", creator=None)
        self.assertIsNone(r.created_by)
        self.assertEqual(r.created_by_name, "")

    def test_str_returns_name(self):
        r = _make_region("Crystalspire")
        self.assertEqual(str(r), "Crystalspire")

    def test_member_count_zero_when_no_rooms(self):
        r = _make_region()
        self.assertEqual(r.member_count(), 0)

    def test_member_count_increments_with_membership(self):
        r = _make_region()
        RegionMembership.objects.create(
            region=r,
            room=self.room1,
            room_name=self.room1.key,
        )
        self.assertEqual(r.member_count(), 1)

    def test_default_manager_excludes_archived(self):
        r = _make_region("Hidden Vale")
        r.archive(editor=self.char1)
        self.assertNotIn(r, Region.objects.all())

    def test_all_objects_includes_archived(self):
        r = _make_region("Hidden Vale")
        r.archive(editor=self.char1)
        self.assertIn(r, Region.all_objects.all())

    def test_ordering_is_alphabetical(self):
        _make_region("Zebra Zone")
        _make_region("Alpha Area")
        names = list(Region.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names))


class TestRegionSignal(EvenniaTest):
    """region_created fires when create_region is called."""

    def test_signal_fires_on_create(self):
        with patch("evennia_regions.signals.region_created.send") as mock_send:
            r = Region.create_region("Signal Test", creator=self.char1)
        mock_send.assert_called_once_with(sender=Region, region=r, creator=self.char1)


# ---------------------------------------------------------------------------
# RegionMembership tests
# ---------------------------------------------------------------------------


class TestRegionMembership(EvenniaTest):
    """RegionMembership uniqueness and __str__."""

    def setUp(self):
        super().setUp()
        self.region_a = _make_region("Region A")
        self.region_b = _make_region("Region B")

    def test_create_membership(self):
        m = RegionMembership.objects.create(
            region=self.region_a,
            room=self.room1,
            room_name=self.room1.key,
        )
        self.assertEqual(m.region, self.region_a)
        self.assertEqual(m.room, self.room1)

    def test_room_can_belong_to_multiple_regions(self):
        RegionMembership.objects.create(
            region=self.region_a,
            room=self.room1,
            room_name=self.room1.key,
        )
        RegionMembership.objects.create(
            region=self.region_b,
            room=self.room1,
            room_name=self.room1.key,
        )
        self.assertEqual(RegionMembership.objects.filter(room=self.room1).count(), 2)

    def test_only_one_primary_per_room(self):
        RegionMembership.objects.create(
            region=self.region_a,
            room=self.room1,
            room_name=self.room1.key,
            is_primary=True,
        )
        # Wrap in a savepoint so the broken transaction doesn't bleed into tearDown.
        with transaction.atomic(), self.assertRaises(IntegrityError):
            RegionMembership.objects.create(
                region=self.region_b,
                room=self.room1,
                room_name=self.room1.key,
                is_primary=True,
            )

    def test_primary_for_returns_flagged_membership(self):
        RegionMembership.objects.create(
            region=self.region_a, room=self.room1, room_name=self.room1.key
        )
        primary = RegionMembership.objects.create(
            region=self.region_b, room=self.room1, room_name=self.room1.key, is_primary=True
        )
        self.assertEqual(RegionMembership.primary_for(self.room1.pk), primary)

    def test_primary_for_falls_back_to_earliest(self):
        first = RegionMembership.objects.create(
            region=self.region_a, room=self.room1, room_name=self.room1.key
        )
        RegionMembership.objects.create(
            region=self.region_b, room=self.room1, room_name=self.room1.key
        )
        self.assertEqual(RegionMembership.primary_for(self.room1.pk), first)

    def test_primary_for_none_when_no_membership(self):
        self.assertIsNone(RegionMembership.primary_for(self.room1.pk))

    def test_same_room_cannot_join_same_region_twice(self):
        """Without this constraint member_count() double-counts one room."""
        RegionMembership.objects.create(
            region=self.region_a, room=self.room1, room_name=self.room1.key
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            RegionMembership.objects.create(
                region=self.region_a, room=self.room1, room_name=self.room1.key
            )

    def test_create_link_is_idempotent(self):
        """AbstractLink.create_link get_or_creates on the unique pair.

        Also pins the README's documented call shape: AbstractAuthoredLink
        takes linked_by= (deriving created_by_name), not created_by=.
        """
        first, created_first = RegionMembership.create_link(
            self.region_a, self.room1, linked_by=self.char1, room_name=self.room1.key
        )
        second, created_second = RegionMembership.create_link(
            self.region_a, self.room1, linked_by=self.char1, room_name=self.room1.key
        )
        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.created_by, self.char1)
        self.assertEqual(first.created_by_name, self.char1.key)

    def test_str_contains_room_and_region_names(self):
        m = RegionMembership.objects.create(
            region=self.region_a,
            room=self.room1,
            room_name="The Grand Hall",
        )
        self.assertIn("The Grand Hall", str(m))
        self.assertIn("Region A", str(m))


# ---------------------------------------------------------------------------
# CmdRegion command tests
# ---------------------------------------------------------------------------


class TestCmdRegionBare(EvenniaCommandTest):
    """Bare +region lists all regions."""

    def test_list_shows_region_name(self):
        _make_region("The Wetlands")
        result = self.call(CmdRegion(), "", caller=self.char1)
        self.assertIn("The Wetlands", result)

    def test_list_empty_message_when_no_regions(self):
        result = self.call(CmdRegion(), "", caller=self.char1)
        self.assertIn("No regions", result)

    def test_list_shows_room_count(self):
        r = _make_region("The Moors")
        RegionMembership.objects.create(region=r, room=self.room1, room_name=self.room1.key)
        result = self.call(CmdRegion(), "", caller=self.char1)
        self.assertIn("1 room", result)


class TestCmdRegionView(EvenniaCommandTest):
    """CmdRegion /view switch."""

    def setUp(self):
        super().setUp()
        self.region = _make_region("Thornwood")

    def test_view_shows_name_and_description(self):
        result = self.call(CmdRegion(), "/view Thornwood", caller=self.char1)
        self.assertIn("Thornwood", result)
        self.assertIn("Wide open fields.", result)

    def test_view_missing_name_shows_usage(self):
        result = self.call(CmdRegion(), "/view", caller=self.char1)
        self.assertIn("Usage", result)

    def test_view_unknown_region_shows_error(self):
        result = self.call(CmdRegion(), "/view Nonexistent", caller=self.char1)
        self.assertIn("No region named", result)

    def test_view_shows_member_rooms(self):
        RegionMembership.objects.create(
            region=self.region, room=self.room1, room_name=self.room1.key
        )
        result = self.call(CmdRegion(), "/view Thornwood", caller=self.char1)
        self.assertIn(self.room1.key, result)


class TestCmdRegionHere(EvenniaCommandTest):
    """+region/here shows current room's region(s)."""

    def test_here_shows_region_when_assigned(self):
        r = _make_region("Ember Plains")
        RegionMembership.objects.create(region=r, room=self.room1, room_name=self.room1.key)
        # char1 is located in room1 by default in EvenniaCommandTest
        result = self.call(CmdRegion(), "/here", caller=self.char1)
        self.assertIn("Ember Plains", result)

    def test_here_shows_no_region_when_unassigned(self):
        result = self.call(CmdRegion(), "/here", caller=self.char1)
        self.assertIn("not been assigned", result)

    def test_here_lists_multiple_regions_and_stars_primary(self):
        r_a = _make_region("Kingdom")
        r_b = _make_region("Fief")
        RegionMembership.objects.create(
            region=r_a, room=self.room1, room_name=self.room1.key, is_primary=True
        )
        RegionMembership.objects.create(region=r_b, room=self.room1, room_name=self.room1.key)
        result = self.call(CmdRegion(), "/here", caller=self.char1)
        self.assertIn("Kingdom", result)
        self.assertIn("Fief", result)
        self.assertIn("primary", result)


class TestCmdRegionCreate(EvenniaCommandTest):
    """+region/create — staff only."""

    def test_create_makes_region(self):
        self.call(
            CmdRegion(),
            "/create Frostreach=A cold northern expanse.",
            caller=self.char1,
        )
        self.assertTrue(Region.objects.filter(name="Frostreach").exists())

    def test_create_player_denied(self):
        result = self.call(CmdRegion(), "/create Denied=Desc", caller=self.char2)
        self.assertIn("staff permissions", result)
        self.assertFalse(Region.objects.filter(name="Denied").exists())

    def test_create_duplicate_name_shows_error(self):
        _make_region("Dusthaven")
        result = self.call(CmdRegion(), "/create Dusthaven=A copy.", caller=self.char1)
        self.assertIn("already exists", result)
        self.assertEqual(Region.objects.filter(name__iexact="Dusthaven").count(), 1)

    def test_create_missing_args_shows_usage(self):
        result = self.call(CmdRegion(), "/create", caller=self.char1)
        self.assertIn("Usage", result)


class TestCmdRegionAddRoom(EvenniaCommandTest):
    """+region/add-room and +region/here-add."""

    def setUp(self):
        super().setUp()
        self.region = _make_region("Saltmarsh")

    def test_here_add_assigns_current_room(self):
        self.call(CmdRegion(), "/here-add Saltmarsh", caller=self.char1)
        self.assertTrue(
            RegionMembership.objects.filter(region=self.region, room=self.room1).exists()
        )

    def test_here_add_adds_second_region_without_removing_first(self):
        other = _make_region("Dustfields")
        RegionMembership.objects.create(
            region=other, room=self.room1, room_name=self.room1.key, is_primary=True
        )
        self.call(CmdRegion(), "/here-add Saltmarsh", caller=self.char1)
        self.assertTrue(RegionMembership.objects.filter(region=other, room=self.room1).exists())
        self.assertTrue(
            RegionMembership.objects.filter(region=self.region, room=self.room1).exists()
        )
        self.assertEqual(RegionMembership.objects.filter(room=self.room1).count(), 2)

    def test_here_add_first_membership_is_primary(self):
        self.call(CmdRegion(), "/here-add Saltmarsh", caller=self.char1)
        m = RegionMembership.objects.get(region=self.region, room=self.room1)
        self.assertTrue(m.is_primary)

    def test_here_add_already_member_is_noop(self):
        RegionMembership.objects.create(
            region=self.region, room=self.room1, room_name=self.room1.key, is_primary=True
        )
        result = self.call(CmdRegion(), "/here-add Saltmarsh", caller=self.char1)
        self.assertIn("already in region", result)
        self.assertEqual(RegionMembership.objects.filter(room=self.room1).count(), 1)

    def test_here_add_player_denied(self):
        result = self.call(CmdRegion(), "/here-add Saltmarsh", caller=self.char2)
        self.assertIn("staff permissions", result)

    def test_here_add_unknown_region_shows_error(self):
        result = self.call(CmdRegion(), "/here-add Nowhere", caller=self.char1)
        self.assertIn("No region named", result)


class TestCmdRegionPrimary(EvenniaCommandTest):
    """+region/primary switch."""

    def setUp(self):
        super().setUp()
        self.region_a = _make_region("Kingdom")
        self.region_b = _make_region("Fief")
        RegionMembership.objects.create(
            region=self.region_a, room=self.room1, room_name=self.room1.key, is_primary=True
        )
        RegionMembership.objects.create(
            region=self.region_b, room=self.room1, room_name=self.room1.key
        )

    def test_primary_reassigns(self):
        self.call(CmdRegion(), f"/primary Fief=#{self.room1.id}", caller=self.char1)
        self.assertTrue(
            RegionMembership.objects.get(region=self.region_b, room=self.room1).is_primary
        )
        self.assertFalse(
            RegionMembership.objects.get(region=self.region_a, room=self.room1).is_primary
        )

    def test_primary_player_denied(self):
        result = self.call(CmdRegion(), f"/primary Fief=#{self.room1.id}", caller=self.char2)
        self.assertIn("staff permissions", result)
        self.assertTrue(
            RegionMembership.objects.get(region=self.region_a, room=self.room1).is_primary
        )

    def test_primary_not_a_member_shows_error(self):
        _make_region("Nowhere Region")
        result = self.call(
            CmdRegion(), f"/primary Nowhere Region=#{self.room1.id}", caller=self.char1
        )
        self.assertIn("not a member", result)

    def test_primary_here_form_uses_current_room(self):
        # char1 is in room1 by default; omitting the dbref targets it.
        self.call(CmdRegion(), "/primary Fief", caller=self.char1)
        self.assertTrue(
            RegionMembership.objects.get(region=self.region_b, room=self.room1).is_primary
        )
        self.assertFalse(
            RegionMembership.objects.get(region=self.region_a, room=self.room1).is_primary
        )

    def test_primary_missing_name_shows_usage(self):
        result = self.call(CmdRegion(), "/primary", caller=self.char1)
        self.assertIn("Usage", result)


class TestCmdRegionRemoveRoom(EvenniaCommandTest):
    """+region/remove-room."""

    def setUp(self):
        super().setUp()
        self.region = _make_region("Ironwall")
        RegionMembership.objects.create(
            region=self.region, room=self.room1, room_name=self.room1.key
        )

    def test_remove_room_player_denied(self):
        result = self.call(
            CmdRegion(), f"/remove-room Ironwall=#{self.room1.id}", caller=self.char2
        )
        self.assertIn("staff permissions", result)
        self.assertTrue(RegionMembership.objects.filter(room=self.room1).exists())

    def test_remove_room_deletes_only_that_membership(self):
        other = _make_region("Stonekeep")
        RegionMembership.objects.create(region=other, room=self.room1, room_name=self.room1.key)
        self.call(CmdRegion(), f"/remove-room Ironwall=#{self.room1.id}", caller=self.char1)
        self.assertFalse(
            RegionMembership.objects.filter(region=self.region, room=self.room1).exists()
        )
        self.assertTrue(RegionMembership.objects.filter(region=other, room=self.room1).exists())

    def test_removing_primary_promotes_earliest_survivor(self):
        RegionMembership.objects.filter(region=self.region, room=self.room1).update(is_primary=True)
        survivor = RegionMembership.objects.create(
            region=_make_region("Stonekeep"), room=self.room1, room_name=self.room1.key
        )
        result = self.call(
            CmdRegion(), f"/remove-room Ironwall=#{self.room1.id}", caller=self.char1
        )
        survivor.refresh_from_db()
        self.assertTrue(survivor.is_primary)
        self.assertIn("primary region", result)

    def test_removing_non_primary_leaves_primary_alone(self):
        primary = RegionMembership.objects.create(
            region=_make_region("Stonekeep"),
            room=self.room1,
            room_name=self.room1.key,
            is_primary=True,
        )
        self.call(CmdRegion(), f"/remove-room Ironwall=#{self.room1.id}", caller=self.char1)
        primary.refresh_from_db()
        self.assertTrue(primary.is_primary)

    def test_remove_last_membership_leaves_room_regionless(self):
        self.call(CmdRegion(), f"/remove-room Ironwall=#{self.room1.id}", caller=self.char1)
        self.assertFalse(RegionMembership.objects.filter(room=self.room1).exists())


# ---------------------------------------------------------------------------
# permissions.is_room_web_visible tests
# ---------------------------------------------------------------------------


class TestIsRoomWebVisible(EvenniaTest):
    """The default rule and the REGIONS_ROOM_VISIBILITY override seam.

    This is the contrib's only privacy predicate, so the cases that matter
    most are the ones where it must answer *False*. A version of this class
    asserting only the True cases passes happily while the helper hides
    nothing at all — which is how the plain-Attribute gap below survived
    the first pass.
    """

    def test_default_rule_visible_when_nothing_is_flagged(self):
        self.assertTrue(is_room_web_visible(self.room1))

    # -- the default rule must actually hide, under either storage form --

    def test_staff_room_hidden_via_plain_attribute(self):
        """A game that flags rooms with room.db.<flag>, not AttributeProperty.

        getattr() never consults the AttributeHandler, so reading the flag
        with getattr alone reports "ic" for a room the game has explicitly
        marked staff, and the region page publishes it.
        """
        self.room1.db.room_type = "staff"
        self.assertFalse(is_room_web_visible(self.room1))

    def test_secret_room_hidden_via_plain_attribute(self):
        self.room1.db.allow_teleport = "secret"
        self.assertFalse(is_room_web_visible(self.room1))

    def test_staff_room_hidden_via_typeclass_attribute(self):
        """The storage form the source game uses — a typeclass-level value."""
        with patch.object(type(self.room1), "room_type", "staff", create=True):
            self.assertFalse(is_room_web_visible(self.room1))

    def test_permissive_class_default_does_not_shadow_a_staff_attribute(self):
        """A plain class attribute must not override an Attribute that hides.

        getattr() finds the class default and stops; if that were the only
        source consulted, a game whose Room typeclass carries a non-descriptor
        `room_type = "ic"` default would publish every room it had marked
        staff via room.db.
        """
        self.room1.db.room_type = "staff"
        with patch.object(type(self.room1), "room_type", "ic", create=True):
            self.assertFalse(is_room_web_visible(self.room1))

    def test_ordinary_flag_values_stay_visible(self):
        self.room1.db.room_type = "ic"
        self.room1.db.allow_teleport = "public"
        self.assertTrue(is_room_web_visible(self.room1))

    # -- the override seam --

    def test_override_used_when_configured(self):
        with override_settings(REGIONS_ROOM_VISIBILITY="evennia_regions.tests._always_hidden"):
            self.assertFalse(is_room_web_visible(self.room1))

    def test_override_is_the_whole_answer_not_an_extra_filter(self):
        self.room1.db.room_type = "staff"
        with override_settings(REGIONS_ROOM_VISIBILITY="evennia_regions.tests._always_visible"):
            self.assertTrue(is_room_web_visible(self.room1))

    # -- misconfiguration must fail CLOSED, never back to the looser default --

    def test_dotless_override_path_hides_rather_than_falling_back(self):
        with override_settings(REGIONS_ROOM_VISIBILITY="not_a_dotted_path"):
            self.assertFalse(is_room_web_visible(self.room1))

    def test_missing_attribute_override_hides_and_does_not_raise(self):
        """Valid module, wrong attribute name: resolve_dotted raises AttributeError."""
        with override_settings(REGIONS_ROOM_VISIBILITY="evennia_regions.permissions.no_such_fn"):
            self.assertFalse(is_room_web_visible(self.room1))

    def test_unimportable_module_override_hides(self):
        with override_settings(REGIONS_ROOM_VISIBILITY="no_such_module_at_all.rule"):
            self.assertFalse(is_room_web_visible(self.room1))

    def test_override_resolving_to_none_hides(self):
        with override_settings(REGIONS_ROOM_VISIBILITY="evennia_regions.tests._NOT_CALLABLE"):
            self.assertFalse(is_room_web_visible(self.room1))

    def test_override_raising_at_call_time_hides(self):
        with override_settings(REGIONS_ROOM_VISIBILITY="evennia_regions.tests._exploding_rule"):
            self.assertFalse(is_room_web_visible(self.room1))


# ---------------------------------------------------------------------------
# Web view tests
# ---------------------------------------------------------------------------


class TestRegionListView(EvenniaTest):
    """RegionListView returns 200 and lists regions.

    Uses RequestFactory + direct view call, both to avoid the Evennia
    template context RecursionError that triggers when Django's TestClient
    tries to copy() the context, and because evennia_regions.urls is not
    wired into any ROOT_URLCONF during a contrib-only test run — the view
    is invoked directly rather than resolved through reverse().
    """

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _get(self, url):
        """Make a RequestFactory GET with AnonymousUser set (required by Evennia context processors)."""
        request = self.factory.get(url)
        request.user = AnonymousUser()
        return request

    def test_list_view_ok(self):
        r = _make_region("Web Region")
        request = self._get("/regions/")
        response = RegionListView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        # Check context_data (pre-render) to avoid the Evennia template RecursionError.
        self.assertIn(r, response.context_data["object_list"])

    def test_list_view_empty_returns_200(self):
        request = self._get("/regions/")
        response = RegionListView.as_view()(request)
        self.assertEqual(response.status_code, 200)


class TestRegionDetailView(EvenniaTest):
    """RegionDetailView returns 200 with region data."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _get(self, url):
        request = self.factory.get(url)
        request.user = AnonymousUser()
        return request

    def test_detail_view_ok(self):
        r = _make_region("Detail Region", description="A detailed place.")
        request = self._get(f"/regions/{r.pk}/")
        response = RegionDetailView.as_view()(request, pk=r.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data["region"], r)

    def test_detail_view_404_for_missing(self):
        request = self._get("/regions/99999/")
        with self.assertRaises(Http404):
            RegionDetailView.as_view()(request, pk=99999)

    def test_detail_view_hides_non_visible_rooms_for_non_staff(self):
        r = _make_region("Guarded Vale")
        RegionMembership.objects.create(region=r, room=self.room1, room_name=self.room1.key)
        request = self._get(f"/regions/{r.pk}/")
        with override_settings(REGIONS_ROOM_VISIBILITY="evennia_regions.tests._always_hidden"):
            response = RegionDetailView.as_view()(request, pk=r.pk)
        self.assertEqual(response.context_data["memberships"], [])


# ---------------------------------------------------------------------------
# Web pages: render for real
# ---------------------------------------------------------------------------


@override_settings(ROOT_URLCONF=__name__)
class TestWebPagesRender(EvenniaTest):
    """
    Render both region pages for real.

    The two classes above stop at response.context_data, which compiles no
    template: a ListView returns a lazy TemplateResponse, so a missing
    partial, a typo'd template name or an unreversable URL surfaces only on
    render. These cases call response.render(), against this module's own
    URLconf.

    RequestFactory + direct view invocation rather than Django's TestClient,
    because the TestClient trips an Evennia template-context RecursionError on
    authenticated HTML pages.
    """

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.region = _make_region("Guarded Vale", description="Mist and old stone.")
        # A distinctive room_name, not room1's default key ("Room"): the page's
        # own static text contains "Rooms", so asserting on the key would pass
        # even when the room itself is correctly withheld.
        self.room_name = "Vale Gatehouse"
        RegionMembership.objects.create(
            region=self.region, room=self.room1, room_name=self.room_name, is_primary=True
        )

    def _render(self, view, *, path_="/regions/", user=None, **kwargs):
        request = self.factory.get(path_)
        request.user = AnonymousUser() if user is None else user
        # Evennia's general_context processor reads request.session["puppet"]
        # for any authenticated user, and RequestFactory attaches no session.
        request.session = import_module(settings.SESSION_ENGINE).SessionStore()
        response = view.as_view()(request, **kwargs)
        response.render()
        return response.content.decode()

    # -- region list --------------------------------------------------------

    def test_region_list_renders_names_and_links(self):
        html = self._render(RegionListView)
        self.assertIn("Guarded Vale", html)
        self.assertIn("Mist and old stone.", html)
        self.assertIn(f'href="/regions/{self.region.pk}/"', html)

    def test_region_list_renders_its_empty_state(self):
        Region.objects.all().delete()
        self.assertIn("No regions have been defined yet.", self._render(RegionListView))

    def test_member_counts_are_withheld_from_non_staff(self):
        # A raw count includes rooms the detail page hides, so publishing it
        # tells a visitor exactly how many rooms they are not being shown.
        self.assertNotIn('<th scope="col">Rooms</th>', self._render(RegionListView))

    def test_member_counts_are_rendered_for_staff(self):
        html = self._render(RegionListView, user=self.account)
        self.assertIn('<th scope="col">Rooms</th>', html)

    # -- region detail ------------------------------------------------------

    def test_region_detail_renders_member_rooms(self):
        html = self._render(
            RegionDetailView, path_=f"/regions/{self.region.pk}/", pk=self.region.pk
        )
        self.assertIn("Guarded Vale", html)
        self.assertIn(self.room_name, html)
        self.assertIn("Primary", html)
        self.assertIn("Member Rooms (1)", html)

    def test_region_detail_omits_hidden_rooms_from_the_rendered_page(self):
        with override_settings(REGIONS_ROOM_VISIBILITY="evennia_regions.tests._always_hidden"):
            html = self._render(
                RegionDetailView, path_=f"/regions/{self.region.pk}/", pk=self.region.pk
            )
        self.assertNotIn(self.room_name, html)
        self.assertIn("No rooms have been assigned to this region yet.", html)
        self.assertIn("Member Rooms (0)", html)

    def test_region_detail_renders_without_a_description(self):
        bare = _make_region("Nameless Waste", description="")
        html = self._render(RegionDetailView, path_=f"/regions/{bare.pk}/", pk=bare.pk)
        self.assertIn("(No description.)", html)


# ---------------------------------------------------------------------------
# Maps integration: the primary_region tile overlay
# ---------------------------------------------------------------------------


class TestMapsOverlayProvider(EvenniaTest):
    """
    The primary_region overlay provider.

    Behaviour is tested by calling provide() directly, so these cases run
    whether or not evennia_maps is installed — the provider module imports
    nothing from it. The wiring is asserted separately below.
    """

    def _provide(self, *rooms, staff=False):
        return maps_overlays.provide(sender=None, room_ids=[room.id for room in rooms], staff=staff)

    def test_room_with_a_membership_gets_its_region(self):
        region = _make_region("The Grasslands")
        RegionMembership.objects.create(region=region, room=self.room1)
        overlays = self._provide(self.room1)
        self.assertEqual(
            overlays["primary_region"][self.room1.id],
            {"id": region.pk, "name": "The Grasslands"},
        )

    def test_room_without_a_membership_is_absent(self):
        _make_region("The Grasslands")
        self.assertEqual(self._provide(self.room1), {"primary_region": {}})

    def test_flagged_primary_wins_over_an_earlier_membership(self):
        first = _make_region("The Kingdom")
        second = _make_region("The Fief")
        RegionMembership.objects.create(region=first, room=self.room1)
        RegionMembership.objects.create(region=second, room=self.room1, is_primary=True)
        overlays = self._provide(self.room1)
        self.assertEqual(overlays["primary_region"][self.room1.id]["id"], second.pk)

    def test_answer_agrees_with_primary_for(self):
        # The bulk path and primary_for() must not drift apart; that they
        # order identically is the only reason a scalar consumer and the map
        # ever name the same region.
        first = _make_region("The Kingdom")
        second = _make_region("The Fief")
        RegionMembership.objects.create(region=first, room=self.room1)
        RegionMembership.objects.create(region=second, room=self.room1)
        overlays = self._provide(self.room1)
        self.assertEqual(
            overlays["primary_region"][self.room1.id]["id"],
            RegionMembership.primary_for(self.room1.id).region_id,
        )

    def test_archived_region_is_skipped_for_the_next_visible_one(self):
        # An archived region 404s on its own detail page, so linking a tile
        # to it would be worse than showing the room's other region.
        archived = _make_region("Sunken Vale")
        visible = _make_region("The Grasslands")
        RegionMembership.objects.create(region=archived, room=self.room1, is_primary=True)
        RegionMembership.objects.create(region=visible, room=self.room1)
        # While it is visible the flagged primary wins, as primary_for() says.
        overlays = self._provide(self.room1)
        self.assertEqual(overlays["primary_region"][self.room1.id]["id"], archived.pk)
        archived.archive()
        overlays = self._provide(self.room1)
        self.assertEqual(overlays["primary_region"][self.room1.id]["id"], visible.pk)

    def test_room_whose_only_region_is_archived_is_absent(self):
        archived = _make_region("Sunken Vale")
        RegionMembership.objects.create(region=archived, room=self.room1)
        archived.archive()
        self.assertEqual(self._provide(self.room1), {"primary_region": {}})

    def test_staff_flag_does_not_change_the_answer(self):
        region = _make_region("The Grasslands")
        RegionMembership.objects.create(region=region, room=self.room1)
        self.assertEqual(
            self._provide(self.room1, staff=False), self._provide(self.room1, staff=True)
        )

    def test_empty_room_ids_returns_nothing(self):
        self.assertEqual(maps_overlays.provide(sender=None, room_ids=[], staff=False), {})

    def test_query_count_is_flat_in_room_count(self):
        # The whole overlay design rests on this: one map render, one query
        # per overlay, no matter how big the plane.
        region = _make_region("The Grasslands")
        RegionMembership.objects.create(region=region, room=self.room1)
        RegionMembership.objects.create(region=region, room=self.room2)
        with self.assertNumQueries(1):
            self._provide(self.room1)
        with self.assertNumQueries(1):
            self._provide(self.room1, self.room2)


@unittest.skipUnless(apps.is_installed("evennia_maps"), "requires evennia_maps")
class TestMapsOverlayWiring(EvenniaTest):
    """RegionsConfig.ready() connected the provider to the map's collector."""

    def test_map_collects_the_region_overlay(self):
        from evennia_maps.overlays import collect_overlays

        region = _make_region("The Grasslands")
        RegionMembership.objects.create(region=region, room=self.room1)
        overlays = collect_overlays([self.room1.id], staff=False)
        self.assertEqual(overlays["primary_region"][self.room1.id]["name"], "The Grasslands")
