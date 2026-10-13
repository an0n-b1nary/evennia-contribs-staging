"""Award, storefront, seed persistence and rendered Building form seams."""

from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from evennia.utils.test_resources import EvenniaTest
from evennia_building.models import Property
from evennia_economy import seller, stalls
from evennia_economy.models import Storefront
from evennia_plots.models import PlotParticipant, PlotThread
from evennia_rp_resources.models import PlotPayoutRun, ResourceHolding
from typeclasses.characters import Character
from typeclasses.rooms import Room


class M6Seams(EvenniaTest):
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        call_command("seed_sandbox", verbosity=0)

    def test_host_cmdset_exposes_shop_management(self):
        from commands.default_cmdsets import CharacterCmdSet

        self.assertIn("+shop", {command.key for command in CharacterCmdSet().commands})

    def test_reseed_preserves_shop_identity_and_stock_and_approved_budget(self):
        shop = Storefront.objects.get(kind="shop", name="Sample Supply Shop")
        listing_ids = list(shop.listings.filter(status="active").values_list("pk", flat=True))
        call_command("seed_sandbox", verbosity=0)
        self.assertEqual(Storefront.objects.get(kind="shop", name="Sample Supply Shop").pk, shop.pk)
        self.assertEqual(
            list(shop.listings.filter(status="active").values_list("pk", flat=True)), listing_ids
        )
        self.assertEqual(PlotThread.objects.filter(name="The Supply Expedition").count(), 1)

    def test_seeded_shop_is_discoverable_and_a_real_buyer_receives_resource_lot(self):
        from evennia_economy.services import credit

        self.account2.characters.add(self.char2)
        shop = Storefront.objects.get(kind="shop", name="Sample Supply Shop")
        self.assertIn(shop.pk, [store.pk for store, _ in stalls.directory(self.char2)])
        self.char2.location = shop.room
        credit(self.char2, 20)
        stalls.buy(self.char2, shop.listings.get(status="active").pk)
        self.assertEqual(
            ResourceHolding.objects.get(character=self.char2, resource__key="timber").quantity, 2
        )
        self.assertIn("Shops:", shop.room.get_display_footer(self.char2))
        Property.objects.filter(pk=shop.property_id).update(state="archived")
        self.assertNotIn("Sample Supply Shop", shop.room.get_display_footer(self.char2))

    def test_real_character_login_reports_frozen_plot_award(self):
        self.account2.characters.add(self.char2)
        plot = PlotThread.objects.get(name="The Supply Expedition")
        PlotParticipant.objects.create(
            thread=plot, character=self.char2, character_name=self.char2.key
        )
        with self.captureOnCommitCallbacks(execute=True):
            plot.conclude(concluded_by=self.char1)
        self.assertEqual(PlotPayoutRun.objects.get(thread_id=plot.pk).amounts, {"rare-crystal": 2})
        with patch.object(self.char2, "msg") as message:
            self.char2.at_post_puppet()
            self.char2.at_post_puppet()
        awards = [
            call.args[0]
            for call in message.call_args_list
            if call.args and isinstance(call.args[0], str) and "Plot award" in call.args[0]
        ]
        self.assertEqual(len(awards), 1)

    def test_system_seller_stays_off_until_runtime_enable(self):
        from evennia_links import runtime

        self.assertEqual(seller.catalog(self.char2), [])
        runtime.set("RP_ECONOMY_SYSTEM_SELLER", True, by=self.char1)
        self.assertEqual(
            {resource.key for resource, _ in seller.catalog(self.char2)}, {"timber", "scrap"}
        )

    @override_settings(ROOT_URLCONF="world.sandbox.tests")
    def test_rendered_transfer_form_has_explicit_stock_choices(self):
        shop = Storefront.objects.get(kind="shop", name="Sample Supply Shop")
        self.account.characters.add(self.char1)
        self.client.force_login(self.account)
        response = self.client.get(
            reverse("evennia_building:property", args=[shop.property_id]) + "?action=transfer"
        )
        self.assertContains(response, "Return stock to old owner")
        self.assertContains(response, "Transfer stock with shop")
