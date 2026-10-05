"""RP playtest uses actual sheets, catalog effects, scene logs and tracker."""

from decimal import Decimal
from unittest import skipUnless

from django.apps import apps
from django.core.management import call_command
from evennia.utils.test_resources import EvenniaCommandTest

from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.ruleset import get_ruleset
from world.sandbox import content
from world.sandbox.test_rp_partners import RPSeedMixin


@skipUnless(
    all(
        apps.is_installed(label)
        for label in (
            "evennia_rp_chargen",
            "evennia_rp_contest",
            "evennia_scenes",
            "evennia_rptracker",
        )
    ),
    "Full RP playground requires its partners",
)
class TestRPPlayground(RPSeedMixin, EvenniaCommandTest):
    def build_player(self):
        from evennia_rp_chargen import services

        self.char2.location = self.grounds
        for key in get_ruleset().stats:
            services.set_stat(self.char2, key, "B")
        services.finalize(self.char2)

    def test_revised_vocabulary_and_templates(self):
        from evennia_rp_chargen.models import AbilityDefinition, TagDefinition

        self.assertEqual(
            set(get_ruleset().stats),
            {"prowess", "toughness", "wit", "sensitivity", "charisma", "will", "agility"},
        )
        domains = TagDefinition.objects.filter(kind="domain")
        self.assertEqual(domains.count(), 16)
        self.assertEqual(
            set(domains.values_list("name", flat=True)),
            {
                "Acrobatics",
                "Alchemy",
                "Athletics",
                "Deception",
                "Insight",
                "Intimidation",
                "Medicine",
                "Perception",
                "Performance",
                "Persuasion",
                "Ritual",
                "Scholarship",
                "Seduction",
                "Stealth",
                "Survival",
                "Thievery",
            },
        )
        self.assertTrue(all("Suggested:" in row.description for row in domains))
        self.assertEqual(TagDefinition.objects.filter(kind="element").count(), 6)
        self.assertFalse(AbilityDefinition.objects.filter(key="domain-aversion").exists())
        focus = AbilityDefinition.objects.get(key="elemental-focus")
        expertise = AbilityDefinition.objects.get(key="domain-expertise")
        self.assertEqual((focus.budget_cost, focus.max_level), (10, 5))
        self.assertEqual(focus.effects, expertise.effects)
        for key in ("domain-ineptitude", "domain-vulnerability", "elemental-vulnerability"):
            flaw = AbilityDefinition.objects.get(key=key)
            self.assertTrue(flaw.is_flaw)
            self.assertEqual(flaw.budget_cost, 0)

    def test_samples_and_proving_grounds(self):
        from evennia_rp_chargen import abilities
        from evennia_rp_chargen.models import CharacterBuild
        from evennia_rp_contest.models import Challenge

        self.assertEqual(self.grounds.room_type, "ooc")
        plaque = next(obj for obj in self.grounds.contents if obj.key == content.PLAQUE_KEY)
        self.assertIn("+test/set", plaque.db.desc)
        for sample, spec in zip(self.samples, content.RP_SAMPLE_BUILDS, strict=True):
            build = CharacterBuild.objects.get(character=sample)
            self.assertTrue(build.is_playable)
            self.assertEqual(build.allocation_spent, 14)
            self.assertEqual(build.allowance_spent, 0)
            self.assertEqual(abilities.loadout_used(sample), 10)
            for ability, tag in spec["abilities"]:
                self.assertTrue(abilities.find_owned(sample, ability, tag).equipped)
        challenges = list(Challenge.objects.filter(room=self.grounds))
        self.assertEqual([row.number for row in challenges], [1, 2])
        self.assertEqual((challenges[0].stat_key, challenges[0].tag), ("charisma", "performance"))
        self.assertIsNone(challenges[1].stat_key)
        self.assertIsNone(challenges[1].tag)
        self.assertEqual(challenges[1].description, "Cross the chasm")

    def test_catalog_effect_and_private_scene_output(self):
        from evennia_rp_chargen import locks
        from evennia_rp_contest import services
        from evennia_rp_contest.models import Challenge
        from evennia_rp_contest.parsing import parse_test
        from evennia_scenes.models import LogEntry, Scene

        scene = Scene.objects.create(room=self.grounds, room_name=self.grounds.key)
        self.grounds.active_scene_id = scene.pk
        record = services.perform_test(
            self.samples[0], parse_test("#1=Charisma/Performance"), roller=ScriptedRoller([10])
        )
        self.assertTrue(record.is_success)  # B++ + Expertise + 10 narrowly beats A.
        self.assertEqual(record.rating_display, "B ++")
        self.assertEqual(record.scene_id, scene.pk)
        self.assertTrue(locks.is_locked(self.samples[0]))
        log = LogEntry.objects.get(scene=scene)
        self.assertEqual(log.log_type, "system")
        self.assertIn("Performance", log.content)
        for private in ("B ++", "dice", "noise", "55.2"):
            self.assertNotIn(private, log.content)
        scene.close()
        for challenge in Challenge.objects.filter(room=self.grounds):
            # Seeded challenges predate the scene; closing it must not close those.
            self.assertEqual(challenge.status, "open")

    def test_prompt_only_and_alternative_approaches(self):
        from evennia_rp_contest import services
        from evennia_rp_contest.parsing import parse_test

        first = services.perform_test(
            self.samples[1], parse_test("#1=Sensitivity/Water"), roller=ScriptedRoller([0])
        )
        self.assertTrue(first.alternative)
        self.assertEqual(first.tag, "water")
        second = services.perform_test(
            self.samples[1], parse_test("#2=Wit/Ritual"), roller=ScriptedRoller([0])
        )
        self.assertFalse(second.alternative)
        self.assertEqual(second.challenge.number, 2)

    def test_ic_pose_locks_ooc_does_not_and_unlock_is_announced(self):
        from commands.rp import CmdEdge
        from evennia_rp_chargen import locks
        from evennia_rp_chargen.commands import CmdUnlock

        self.build_player()
        self.char2.record_pose("OOC: choosing an approach.", pose_type="ooc")
        self.assertFalse(locks.is_locked(self.char2))
        self.char2.record_pose("studies the gap.", pose_type="pose")
        self.assertTrue(locks.is_locked(self.char2))
        self.assertIn("locked", self.call(CmdEdge(), "/set Wit=2", caller=self.char2))
        self.char1.location = self.grounds
        output = self.call(CmdUnlock(), "", caller=self.char2, receiver=self.char1)
        self.assertIn("unlocks", output)
        self.assertFalse(locks.is_locked(self.char2))
        self.char2.record_pose("commits to the leap.", pose_type="pose")
        self.assertTrue(locks.is_locked(self.char2))

    def test_real_tracker_end_releases_lock_and_closes_challenges(self):
        from evennia_rp_chargen import locks
        from evennia_rp_contest import services
        from evennia_rp_contest.parsing import parse_challenge
        from evennia_rptracker import end_session
        from evennia_rptracker.models import RPSession

        self.build_player()
        self.room2.room_type = "ic"
        self.char1.location = self.room2
        self.char2.location = self.room2
        self.char1.record_pose("offers a hand.", pose_type="pose")
        self.char2.record_pose("takes the hand.", pose_type="pose")
        self.char2.record_pose("steps across.", pose_type="pose")
        self.assertTrue(RPSession.objects.filter(character=self.char2, status="active").exists())
        challenge = services.open_challenge(self.char2, parse_challenge("C~Balance"))
        end_session(self.char2.id)
        self.assertFalse(locks.is_locked(self.char2))
        challenge.refresh_from_db()
        self.assertEqual(challenge.closed_reason, "session_end")

    def test_moving_to_new_room_ends_old_session_then_relocks(self):
        from evennia_rp_chargen import locks

        self.test_real_tracker_end_releases_lock_and_closes_challenges()
        self.char2.record_pose("starts again.", pose_type="pose")
        self.char2.record_pose("keeps talking.", pose_type="pose")
        self.room1.room_type = "ic"
        self.char2.location = self.room1
        self.char2.record_pose("arrives at the next scene.", pose_type="pose")
        self.assertTrue(locks.is_locked(self.char2))

    def test_allowance_purchase_and_upgrade_then_exhaustion_rolls_back(self):
        from evennia_rp_chargen import abilities
        from evennia_rp_chargen.commands import CmdSpend, CmdUpgrade
        from evennia_rp_chargen.models import AbilityTransaction, CharacterBuild
        from evennia_rp_chargen.services import ChargenError

        self.build_player()
        for name in ("Domain Expertise:Performance", "Elemental Focus:Water"):
            self.assertIn("You learn", self.call(CmdSpend(), f"/ability {name}", caller=self.char2))
            self.assertIn("level 2", self.call(CmdUpgrade(), name, caller=self.char2))
        build = CharacterBuild.objects.get(character=self.char2)
        self.assertEqual(build.allowance_spent, Decimal(10))
        transactions = AbilityTransaction.objects.filter(character_id=self.char2.id)
        self.assertEqual(transactions.count(), 4)
        self.assertTrue(all(row.xp_amount == 0 for row in transactions))
        with self.assertRaises(ChargenError):
            abilities.upgrade(self.char2, "elemental-focus", "water")
        self.assertEqual(transactions.count(), 4)
        self.assertEqual(abilities.find_owned(self.char2, "elemental-focus", "water").level, 2)

    def test_reseed_preserves_player_sheet_and_check_audit(self):
        from evennia_rp_chargen import abilities
        from evennia_rp_chargen.models import CharacterBuild
        from evennia_rp_contest import services
        from evennia_rp_contest.models import Challenge
        from evennia_rp_contest.parsing import parse_test

        self.build_player()
        abilities.acquire(self.char2, "elemental-focus", "water")
        record = services.perform_test(self.char2, parse_test("#2=Wit"), roller=ScriptedRoller([0]))
        call_command("seed_sandbox", verbosity=0)
        self.assertEqual(CharacterBuild.objects.count(), 3)
        self.assertEqual(CharacterBuild.objects.get(character=self.char2).allowance_spent, 3)
        self.assertTrue(abilities.find_owned(self.char2, "elemental-focus", "water").equipped)
        self.assertEqual(Challenge.all_objects.count(), 2)
        record.refresh_from_db()
        self.assertIsNone(record.challenge_id)
        self.assertIsNone(record.room_id)
        self.assertTrue(record.detail)
