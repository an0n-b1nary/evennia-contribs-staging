"""Party seams with real sheets, controllers, ignore accounts and guide rendering."""

from copy import deepcopy
from unittest import skipUnless
from unittest.mock import PropertyMock, patch

from django.apps import apps
from django.test import Client, override_settings
from evennia.utils.test_resources import EvenniaCommandTest

from world.sandbox.test_rp_partners import RPSeedMixin


@skipUnless(apps.is_installed("evennia_rp_party"), "Party partner absent")
class TestPartyPlayground(RPSeedMixin, EvenniaCommandTest):
    def opponent(self, actor, side, *, boss=1):
        if not apps.is_installed("evennia_npcs"):
            self.skipTest("optional NPC partner absent")
        from evennia_npcs import services as npcs
        from evennia_rp_combat import services as combat
        from evennia_rp_combat.conf import get

        blueprint = npcs.create_blueprint(
            actor,
            name="Party practice defender",
            kind="template",
            stat_block={stat: "B" for stat in get("RP_COMBAT_ROLES").values()},
        )
        return combat.template(actor, blueprint, side, boss=boss)

    def test_seed_is_opt_in_and_commands_and_guide_are_registered(self):
        from commands.default_cmdsets import CharacterCmdSet
        from evennia_rp_combat import services as combat
        from evennia_rp_party import rules

        state = combat.state_for(self.samples[0])
        self.assertFalse(state["participants"])
        self.assertEqual(
            [row["name"] for row in rules.data(state)["parties"].values()], ["Practice Formation"]
        )
        commands = CharacterCmdSet()
        self.assertIn("+party", {cmd.key for cmd in commands.commands})
        self.assertIn("+bosscheck", {cmd.key for cmd in commands.commands})
        if apps.is_installed("evennia_guides"):
            response = Client().get("/guide/party/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Position and Cover", response.content.decode())
            self.assertIn("Boss Checks", response.content.decode())
            with override_settings(RP_PARTY_REVEALED=False):
                self.assertEqual(Client().get("/guide/party/").status_code, 404)

    def test_real_frozen_builds_npc_cover_public_shot_and_ignore_boundary(self):
        from evennia_rp_combat import services as combat
        from evennia_rp_party import rules, services

        attacker, defender = self.samples
        attacker.account, defender.account = self.account, self.account2
        combat.join(attacker, "one")
        combat.join(defender, "two")
        coverer = self.opponent(attacker, "two")
        key = services.change(defender, "create", "Defenders")
        services.change(attacker, "join", key, subject=coverer)
        services.change(defender, "formation", "back", cover=True)
        services.change(attacker, "formation", "front", subject=coverer)
        exchange = combat.declare(attacker, [defender], bet="reaching", public=True)
        token = f"{exchange}:1"
        preview = services.cover(attacker, defender, token, subject=coverer, preview=True)
        self.assertIn("called a reaching bet publicly", preview)
        self.assertNotIn("Evade:", preview)
        self.assertNotIn("Burst", preview)
        fight = combat.open_fight(self.grounds)
        before = deepcopy(fight.state)
        if apps.is_installed("evennia_social"):
            self.account2.db.ignore_list = [self.account.pk]
            with self.assertRaisesRegex(ValueError, "confirmation"):
                services.cover(attacker, defender, token, subject=coverer)
            fight.refresh_from_db()
            self.assertEqual(fight.state, before)
            self.assertEqual(self.account2.db.ignore_list, [self.account.pk])
            self.account2.db.ignore_list = []
        services.cover(attacker, defender, token, subject=coverer)
        state = combat.state_for(attacker)
        self.assertEqual(state["exchanges"][exchange]["targets"], [str(coverer.pk)])
        self.assertEqual(state["participants"][str(defender.pk)]["hp"], 100)
        self.assertEqual(rules.position(state, coverer.pk), "front")

    def test_real_encore_resistance_and_primary_only_heal_with_repeat_history(self):
        if not apps.is_installed("evennia_rp_chargen"):
            self.skipTest("optional chargen partner absent")
        from evennia_rp_chargen import abilities, locks
        from evennia_rp_combat import services as combat
        from evennia_rp_party import services

        actor, ally = self.samples
        for subject in self.samples:
            locks.unlock(subject)
        abilities.grant(actor, "proficiency", "performance")
        abilities.grant(ally, "domain-resistance", "performance")
        combat.join(actor, "one")
        combat.join(ally, "one")
        self.opponent(actor, "two")
        key = services.change(actor, "create", "Support")
        services.change(ally, "join", key)
        combat.storyteller(actor, "vitality", target=actor, value=50)
        combat.storyteller(ally, "vitality", target=ally, value=50)
        combat.control(actor, "accept")
        combat.control(ally, "accept")
        exchange = combat.declare(
            actor,
            [ally],
            domain="performance",
            improvised={"action": "assist", "effects": ["heal"]},
        )
        state = combat.state_for(actor)
        own, other = state["participants"][str(actor.pk)], state["participants"][str(ally.pk)]
        self.assertGreater(own["spirit"], 0)
        self.assertGreater(other["spirit"], 0)
        self.assertEqual(own["hp"], 50)
        self.assertGreater(other["hp"], 50)
        self.assertEqual(state["exchanges"][exchange]["resolved"], 1)
        self.assertIn(f"assist:{actor.pk}", own["support_history"])
        self.assertIn(f"assist:{ally.pk}", own["support_history"])

    def test_transient_chat_routes_only_connected_roster_with_ignore_filtering(self):
        from evennia_rp_combat import services as combat
        from evennia_rp_party import services

        first, second = self.samples
        first.account, second.account = self.account, self.account2
        combat.join(first, "one")
        combat.join(second, "one")
        key = services.change(first, "create", "Private coordination")
        services.change(second, "join", key)
        fight = combat.open_fight(self.grounds)
        before, entries = deepcopy(fight.state), fight.entries.count()
        with (
            patch(
                "evennia.accounts.accounts.DefaultAccount.is_connected",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch.object(first, "msg") as one,
            patch.object(second, "msg") as two,
        ):
            self.assertEqual(services.chat(first, "Transient secret"), 2)
            one.assert_called_once()
            two.assert_called_once()
            if apps.is_installed("evennia_social"):
                self.account2.db.ignore_list = [self.account.pk]
                self.assertEqual(services.chat(first, "Filtered secret"), 1)
                self.assertEqual(two.call_count, 1)
        fight.refresh_from_db()
        self.assertEqual(fight.state, before)
        self.assertEqual(fight.entries.count(), entries)

    def test_manual_npc_boss_checks_ignore_consent_shelving_and_bound_contest(self):
        from evennia_rp_combat import engine
        from evennia_rp_combat import services as combat
        from evennia_rp_party import boss, boss_services, services

        from evennia_rp_rules.dice import ScriptedRoller

        first, second = self.samples
        first.account, second.account = self.account, self.account2
        combat.join(first, "heroes")
        combat.join(second, "heroes")
        opponent = self.opponent(first, "boss", boss=3)
        key = services.change(first, "create", "Check defenders")
        services.change(second, "join", key)
        services.change(first, "formation", "front")
        services.change(second, "formation", "front")
        if apps.is_installed("evennia_social"):
            self.account2.db.ignore_list = [self.account.pk]
            with self.assertRaisesRegex(ValueError, "confirmation"):
                boss_services.issue(first, [key], "tank", subject=opponent)
            self.account2.db.ignore_list = []
        ident = boss_services.issue(first, [key], "tank", subject=opponent)[0]
        fight = combat.open_fight(self.grounds)
        before = deepcopy(combat.state_for(first)["participants"][str(opponent.pk)])
        combat.shelve(first, "Manual Check intermission")
        combat.unshelve(first, fight.pk)
        for subject in (first, second, opponent):
            combat.join(first if subject == opponent else subject, subject=subject)
        combat.storyteller(first, "resume")
        self.assertEqual(boss.get(combat.state_for(first), ident)["status"], "pending")
        view = boss_services.preview(first, ident, subject=opponent)
        outcome = boss_services.resolve(
            first, ident, view["token"], subject=opponent, acknowledgment="Both defenders are ready"
        )
        self.assertTrue(outcome["passed"])
        state = combat.state_for(first)
        row = state["participants"][str(opponent.pk)]
        self.assertEqual(row["actions_spent"], before["actions_spent"])
        self.assertEqual(row["clock"], before["clock"])
        self.assertEqual(engine.value(row, "staggered"), 30)
        if not apps.is_installed("evennia_rp_contest"):
            return
        from evennia_rp_contest.models import CheckRecord
        from evennia_rp_contest.narration import public_text

        ident = boss_services.issue(
            first, [key], "contest", subject=opponent, approaches=("intellect",)
        )[0]
        attempt = boss_services.roll(second, ident, "intellect", roller=ScriptedRoller([0]))
        record = CheckRecord.objects.get(pk=attempt["record"])
        self.assertIsNone(record.challenge)
        self.assertEqual(record.detail["binding"]["check"], ident)
        with override_settings(RP_CONTEST_SHOW_RATINGS_TO_ROOM=True):
            self.assertNotIn(" vs ", public_text(record))
        boss_services.cancel(first, ident)
        self.assertEqual(boss.get(combat.state_for(first), ident)["status"], "canceled")

    def test_real_team_surge_snapshots_cover_and_restore_use_one_combat_journal(self):
        from evennia_rp_combat import services as combat
        from evennia_rp_party import rules, services, synergy

        attacker, defender = self.samples
        combat.join(attacker, "one")
        combat.join(defender, "two")
        coverer = self.opponent(attacker, "two")
        attacking = services.change(attacker, "create", "Surging")
        defending = services.change(defender, "create", "Covering")
        services.change(attacker, "join", defending, subject=coverer)
        services.change(defender, "formation", "back", cover=True)
        services.change(attacker, "formation", "front", subject=coverer)
        # Host fixture only; there is no player command that sets Synergy.
        combat.execute(
            attacker,
            "fixture party balance",
            lambda state: rules.party(state, attacking).update(synergy="100"),
        )
        ex = services.surge(attacker, [defender], operation_id="sandbox-surge")
        fight = combat.open_fight(self.grounds)
        self.assertIn("reserved 100 Synergy", fight.entries.latest("sequence").summary)
        before = combat.state_for(attacker)
        self.assertEqual(synergy.held(before, attacking), 100)
        services.cover(attacker, defender, f"{ex}:1", subject=coverer)
        state = combat.state_for(attacker)
        self.assertEqual(rules.data(state)["surges"][f"{ex}:1"]["status"], "executed")
        self.assertEqual(state["participants"][str(defender.pk)]["hp"], 100)
        self.assertEqual(synergy.pool(state, attacking), 10)
        self.assertGreater(synergy.pool(state, defending), 0)
        self.assertEqual(state["participants"][str(attacker.pk)]["clock"], 1)
        self.assertEqual(services.surge(attacker, [defender], operation_id="sandbox-surge"), ex)
        self.assertEqual(combat.state_for(attacker), state)
