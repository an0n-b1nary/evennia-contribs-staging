# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Reference game seam: the live map's room panel with every partner installed."""

from evennia.utils.test_resources import EvenniaTest
from rest_framework.test import APIClient
from typeclasses.characters import Character
from typeclasses.rooms import Room

from world.sandbox.seeding import SeededSandboxMixin
from world.sandbox.tests import _search_room


class TestSeededRoomPanel(SeededSandboxMixin, EvenniaTest):
    """
    Market Row has it all: lore in its region (the Commons), a plot thread
    through its market-day scene, and urban terrain with scrap to gather.
    """

    room_typeclass = Room
    character_typeclass = Character

    def setUp(self):
        super().setUp()
        from evennia_maps.models import MapPlane
        from world.sandbox import content

        self.plane = MapPlane.objects.get(name=content.PLANE_NAME)
        self.market = _search_room("Market Row")
        # The website acts as a character on the account's roster; EvenniaTest
        # leaves account2's empty, which would make every viewer None.
        self.account2.characters.add(self.char2)

    def _detail(self, account):
        client = APIClient()
        client.force_authenticate(account)
        response = client.get(
            f"/api/v1/planes/{self.plane.pk}/tiles/{self.market.pk}/detail/", format="json"
        )
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        detail["by_key"] = {section["key"]: section for section in detail["sections"]}
        return detail

    def test_the_panel_names_the_room_and_links_its_region(self):
        detail = self._detail(self.account2)
        self.assertEqual(detail["room_name"], "Market Row")
        self.assertEqual(detail["region"]["name"], "The Commons")
        self.assertTrue(detail["region"]["url"].startswith("/regions/"))
        self.assertTrue(detail["room_url"])
        self.assertTrue(detail["description"].startswith("[Placeholder]"))
        self.assertEqual(detail["recent_scenes"][0]["title"], "Market Day")

    def test_sections_arrive_in_order(self):
        keys = [section["key"] for section in self._detail(self.account2)["sections"]]
        self.assertEqual(keys, ["lore", "plots", "resources"])

    def test_lore_you_know_is_linked_and_the_rest_locked(self):
        from evennia_lore.models import LoreAcquisition, LoreEntry

        before = self._detail(self.account2)["by_key"]["lore"]
        locked = [item for item in before["items"] if item["locked"]]
        self.assertTrue(locked)
        entry = LoreEntry.objects.get(title=locked[0]["label"])
        LoreAcquisition.objects.create(entry=entry, character=self.char2)
        after = self._detail(self.account2)["by_key"]["lore"]
        known = next(item for item in after["items"] if item["label"] == entry.title)
        self.assertFalse(known["locked"])
        self.assertEqual(known["url"], f"/lore/{entry.pk}/")

    def test_the_plot_through_this_room_is_linked(self):
        plots = self._detail(self.account2)["by_key"]["plots"]
        storm = next(item for item in plots["items"] if item["label"] == "The Founding Storm")
        self.assertTrue(storm["url"].startswith("/plots/"))

    def test_gathering_here_follows_the_terrain(self):
        resources = self._detail(self.account2)["by_key"]["resources"]
        self.assertEqual(
            resources["items"],
            [{"label": "Materials", "note": "Scrap", "url": "", "locked": False}],
        )

    def test_gathering_here_waits_for_the_reveal(self):
        from evennia_links import runtime

        runtime.set("RP_RESOURCES_REVEALED", False)
        try:
            self.assertNotIn("resources", self._detail(self.account2)["by_key"])
            self.assertIn("resources", self._detail(self.account)["by_key"])
        finally:
            runtime.reset("RP_RESOURCES_REVEALED")
