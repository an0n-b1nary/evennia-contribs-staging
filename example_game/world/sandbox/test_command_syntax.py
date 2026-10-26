# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Single-switch commands through the reference game's cmdset and typeclasses."""

import re
from unittest.mock import patch

from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet
from django.db import transaction
from evennia.utils.create import create_object
from evennia.utils.test_resources import EvenniaCommandTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_maps import placement
from evennia_maps.models import MapPlane, RoomTile


class CommandSyntaxSeams(EvenniaCommandTest):
    character_typeclass = Character
    room_typeclass = Room

    def contrib_commands(self):
        # Exercise the final merged set, including contrib stock replacements.
        commands = (CharacterCmdSet() + AccountCmdSet()).commands
        return [cmd for cmd in commands if type(cmd).__module__.startswith("evennia_")]

    def test_every_contrib_command_refuses_bad_switches_before_queries(self):
        commands = self.contrib_commands()
        self.assertGreater(len(commands), 100)
        for registered in commands:
            options = getattr(registered, "switch_options", ()) or ()
            first = next(iter(options), "unknown")
            for args in ("/definitelyunknown", f"/{first}/{first}", f"/{first}/unknown"):
                with self.subTest(command=registered.key, args=args):
                    command = type(registered)()
                    # Also cover a command instance retaining its previous subject.
                    command.subject = self.char1
                    with (
                        patch.object(
                            command, "parse", side_effect=AssertionError("Parsed bad switch")
                        ),
                        self.assertNumQueries(0),
                    ):
                        message = self.call(command, args)
                    self.assertRegex(message.lower(), r"usage|see help")

    def test_every_documented_switch_is_accepted(self):
        # A switch missing from switch_options is now refused, not dropped.
        for registered in self.contrib_commands():
            options = getattr(registered, "switch_options", ()) or ()
            names = {registered.key.lower(), *(alias.lower() for alias in registered.aliases)}
            pattern = rf"(?<![\w+@/])(?:{'|'.join(map(re.escape, names))})/([a-z][\w-]*)"
            for switch in set(re.findall(pattern, (type(registered).__doc__ or "").lower())):
                with self.subTest(command=registered.key, switch=switch):
                    matches = [option for option in options if option == switch] or [
                        option for option in options if option.startswith(switch)
                    ]
                    self.assertEqual(len(matches), 1)

    def test_every_contrib_switch_keeps_numeric_refusals_readable(self):
        for registered in self.contrib_commands():
            for switch in ("", *(getattr(registered, "switch_options", ()) or ())):
                for argument in ("", "not-a-number", "999999999"):
                    args = (f"/{switch} " if switch else " ") + argument
                    with self.subTest(command=registered.key, args=args), transaction.atomic():
                        # Each probe gets its own savepoint, including read commands
                        # whose empty form initializes a record or preference.
                        original_msg = self.char1.msg
                        try:
                            result = self.call(type(registered)(), args)
                        finally:
                            self.char1.msg = original_msg
                            transaction.set_rollback(True)
                        self.assertNotRegex(
                            result,
                            r"invalid literal for int\(|int\(\) argument|could not convert string to float|ConversionSyntax",
                        )

    def test_bad_move_tiers_preserve_signature_and_improvised_drafts(self):
        from evennia.utils.dbserialize import deserialize

        for key, attribute, category in (
            ("+moves", "signature_draft", "rp_chargen"),
            ("+improv", "improvised_move", "rp_combat"),
        ):
            self.call(self.command(key), "/new Syntax draft")
            original = deserialize(self.char1.attributes.get(attribute, category=category))
            self.assertTrue(original)
            for field in ("power", "accuracy"):
                for value in ("", "not-a-number", "1=old form"):
                    with self.subTest(command=key, field=field, value=value):
                        output = self.call(self.command(key), f"/{field} {value}")
                        self.assertIn("Give a whole number", output)
                        self.assertEqual(
                            deserialize(self.char1.attributes.get(attribute, category=category)),
                            original,
                        )

    def expect(self, command, args, text=None, **kwargs):
        output = self.call(command, args, **kwargs)
        if text is not None:
            self.assertIn(text, output)
        return output

    def command(self, key):
        return next(command for command in CharacterCmdSet().commands if command.key == key)

    def test_unhangout_updates_social_directory_and_map_overlay(self):
        from evennia_maps.views import tile_hangout_type

        command = self.command("+roomconfig")
        self.call(command, "/hangout bar")
        self.assertEqual(tile_hangout_type(self.room1), "bar")
        self.call(command, "/hangout/clear")
        self.assertEqual(tile_hangout_type(self.room1), "bar")
        self.call(command, "/unhangout", "Removed Bar hangout designation")
        self.assertIsNone(tile_hangout_type(self.room1))
        result = self.call(self.command("+hangouts"), "/all")
        self.assertNotIn(self.room1.key, result)

    def test_reflow_preview_and_confirmation_preserve_host_room_details(self):
        create_object(
            "typeclasses.exits.Exit", key="north", location=self.room1, destination=self.room2
        )
        self.room2.set_terrain(["urban"])
        plane = MapPlane.objects.create(name="Syntax seam")
        placement.place_tile(self.room1, plane, 0, 0)
        command = self.command("+map")
        self.call(command, f"/reflow/apply #{self.room1.pk}")
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())
        preview = self.call(command, f"/reflow #{self.room1.pk}")
        self.assertFalse(RoomTile.objects.filter(room=self.room2).exists())
        token = re.search(r"Confirm: \+map/reflow #\d+=(\S+)", preview).group(1)
        self.call(command, f"/reflow #{self.room1.pk}={token}")
        tile = RoomTile.objects.get(room=self.room2)
        self.assertEqual(
            (tile.x, tile.y, tile.room_name, tile.terrain), (0, 1, self.room2.key, "urban")
        )

    def test_activity_switch_reads_real_region_totals(self):
        from django.utils import timezone
        from evennia_rptracker.models import RPSession

        from evennia_regions.models import Region, RegionMembership

        region = Region.create_region("Syntax report region", self.char1)
        RegionMembership.objects.create(region=region, room=self.room1, is_primary=True)
        RPSession.objects.create(
            character=self.char1, room=self.room1, activated_at=timezone.now(), status="active"
        )
        command = self.command("+report")
        result = self.call(command, "/activity 1")
        self.assertIn("Region: Syntax report region", result)
        self.assertNotIn("RP activity:", self.call(command, "activity 1"))

    def test_dotted_review_and_withdrawal_use_real_host_forms(self):
        from evennia_jobs.models import RequestDecision, RequestWithdrawal
        from evennia_jobs.review import submit_request

        from world.sandbox import content

        def submit():
            return submit_request(
                author=self.char2,
                form_key="build",
                title="Syntax proposal",
                answers=content.REQUEST_DEMO_ANSWERS,
            )

        proposal = submit()
        number = proposal.job.job_number
        command = self.command("+jobs")
        self.call(command, f"/approve {number} 1=Old syntax")
        self.assertFalse(RequestDecision.objects.filter(submission=proposal).exists())
        reason = "Fits #12.3 # keep the entrance"
        self.call(command, f"/approve #{number}.1 # {reason}")
        self.assertEqual(RequestDecision.objects.get(submission=proposal).reason, reason)
        proposal = submit()
        self.call(
            self.command("+request"),
            f"/withdraw #{proposal.job.job_number}.1 # Rework",
            caller=self.char2,
        )
        self.assertEqual(RequestWithdrawal.objects.get(submission=proposal).reason, "Rework")

    def test_single_ip_lift_switch_preserves_the_audit_history(self):
        from evennia_moderation import services
        from evennia_moderation.models import ModerationAction

        action = services.restrict(
            self.char1, kind="softban", address="192.0.2.0/24", reason="Incident"
        )
        command = self.command("+softban")
        self.assertTrue(command.access(self.char1, "cmd"))
        self.call(command, "/lift/ip 192.0.2.0/24")
        action.refresh_from_db()
        self.assertIsNone(action.lifted_at)
        self.call(command, "/liftip 192.0.2.0/24", "Lifted 1")
        action.refresh_from_db()
        self.assertIsNotNone(action.lifted_at)
        self.assertTrue(ModerationAction.objects.filter(kind="lift").exists())

    def test_xp_grant_uses_the_real_host_ledger_and_staff_lock(self):
        from decimal import Decimal

        from evennia_xp.models import CharacterXP, XPLog

        command = self.command("+xp")
        self.call(command, "/grant Char2=3:Old syntax")
        self.assertFalse(XPLog.objects.exists())
        self.call(command, "/grant Char2=3 # Player attempt", caller=self.char2)
        self.assertFalse(XPLog.objects.exists())
        reason = "Award for #12.3 # A=B"
        self.call(command, f"/grant #{self.char2.pk}=3 # {reason}", "Granted 3 XP")
        self.assertEqual(XPLog.objects.get().reason, reason)
        self.assertEqual(
            CharacterXP.objects.get(character_id=self.char2.pk).current_balance, Decimal("3")
        )

    def test_money_and_resource_adjustments_keep_host_audit_metadata(self):
        from evennia_economy.models import LedgerEntry
        from evennia_economy.services import balance
        from evennia_rp_resources.models import ResourceDefinition, ResourceGrant
        from evennia_rp_resources.services import total_held

        ResourceDefinition.objects.create(key="syntax-timber", name="Timber", category="materials")
        economy, resources = self.command("+economy"), self.command("+resources")
        self.call(economy, "/credit Char2=10,Old syntax")
        self.call(resources, "/grant Char2=syntax-timber,4,Old syntax")
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertFalse(ResourceGrant.objects.exists())
        note = "For #12.3 # A=B"
        self.call(economy, f"/credit #{self.char2.pk}=10 # {note}", "Purse updated")
        self.call(
            resources, f"/grant #{self.char2.pk}=4 syntax-timber # {note}", "Resources updated"
        )
        self.call(economy, "/debit Char2=2 # Used", "Purse updated")
        self.call(resources, "/spend Char2=1 syntax-timber # Used", "Resources updated")
        self.assertEqual((balance(self.char2), total_held(self.char2)), (8, 3))
        for row in (
            LedgerEntry.objects.order_by("pk").first(),
            ResourceGrant.objects.order_by("pk").first(),
        ):
            self.assertEqual((row.note, row.by_id), (note, self.char1.pk))

    def test_ability_addresses_reach_the_host_equipment_guard_and_refund(self):
        from evennia_rp_chargen.catalog import seed_catalog
        from evennia_rp_chargen.models import CharacterAbility
        from evennia_rp_equipment import services as gear

        seed_catalog()
        command = self.command("+chargen")
        self.expect(command, "/grant Char2/Proficiency:Performance=2")
        self.assertFalse(CharacterAbility.objects.exists())
        self.expect(command, "/grant Char2=Proficiency/Performance", "now has")
        self.expect(command, "/level Char2=2", "Proficiency/Performance at level 2")
        copy = CharacterAbility.objects.get(character_id=self.char2.pk)
        item = gear.make(self.char2, "Syntax gloves")
        gear.add_requirement(self.char2, item, "ability Proficiency/Performance")
        gear.wear(self.char2, item)
        self.expect(
            self.command("+abilities"),
            "/unequip Proficiency/Performance",
            "held by",
            caller=self.char2,
        )
        copy.refresh_from_db()
        self.assertTrue(copy.equipped)
        gear.remove(self.char2, item)
        self.expect(command, "/refund Char2=Proficiency/Performance", "Revoked")
        self.assertFalse(CharacterAbility.objects.exists())
        self.expect(command, "/grant Char2=Proficiency/Performance", caller=self.char2)
        self.assertFalse(CharacterAbility.objects.exists())

    def test_npc_fields_reach_host_spawn_ratings_and_combat_profile(self):
        from django.test import override_settings
        from evennia_npcs import services
        from evennia_npcs.models import NPCCombatProfile

        with override_settings(NPCS_COMBAT_PROFILES_REVEALED=True):
            command = self.command("+npc")
            self.expect(command, "/create Syntax Guard=template", "Created")
            blueprint = services.find_blueprint("Syntax Guard")
            self.expect(command, "/stats Syntax Guard=presence:A")
            blueprint.refresh_from_db()
            self.assertEqual(blueprint.stat_block, {})
            self.expect(command, "/stat Syntax Guard/presence=A", "updated")
            self.expect(command, "/stat Syntax Guard/resolve=B", "updated")
            spawned = services.spawn(self.char1, blueprint).spawned_object
            self.assertEqual(spawned.get_rating("presence").rung.key, "a")
            self.expect(command, "/profile Syntax Guard/action_weights.standard=3", "saved")
            self.expect(command, "/profile Syntax Guard/reaction_policy.appetite=cautious", "saved")
            self.expect(command, '/profile Syntax Guard={"target_policy":"lowest_vitality"}')
            profile = NPCCombatProfile.objects.get(blueprint=blueprint)
            self.assertEqual(profile.action_weights, {"standard": 3})
            self.assertEqual(profile.reaction_policy, {"appetite": "cautious"})
            self.assertEqual(profile.target_policy, "random")

    def test_lore_author_configures_pending_entry_with_real_scene_and_plot_links(self):
        from unittest.mock import patch

        from django.test import override_settings
        from evennia_lore.commands import _lore_submit_save
        from evennia_lore.models import LoreEntry, LoreSceneLink, PlotLoreLink
        from evennia_plots.models import PlotThread
        from evennia_scenes.models import Scene

        scene = Scene.objects.create(title="Syntax scene", room=self.room1, creator=self.char2)
        plot = PlotThread.create_thread("Syntax plot", self.char2)
        command = self.command("+lore")
        with override_settings(LORE_REQUIRE_APPROVAL=True):
            with patch("evennia_links.editing.EvEditor") as editor:
                self.expect(command, "/submit/rumor Old syntax", "one switch", caller=self.char2)
                editor.assert_not_called()
                self.call(command, "/submit Syntax account", caller=self.char2)
                editor.assert_called_once()
            _lore_submit_save(self.char2, "An account of the syntax scene.")
        entry = LoreEntry.objects.get(title="Syntax account")
        number = entry.entry_number
        self.expect(command, f"/kind #{number}=rumor", "now a Rumor", caller=self.char2)
        self.expect(
            command, f"/scene #{number}={scene.scene_number}", "Linked scene", caller=self.char2
        )
        self.expect(
            command, f"/plot #{number}=#{plot.plot_number}", "Linked entry", caller=self.char2
        )
        self.expect(command, f"/tag/major #{number}=Syntax theme", "one switch")
        self.assertFalse(entry.tags.exists())
        self.expect(command, f"/major #{number}=Syntax theme", "Only staff", caller=self.char2)
        self.expect(command, f"/major #{number}=Syntax theme", "created and added")
        self.assertTrue(entry.tags.get().is_major)
        self.assertEqual(LoreSceneLink.objects.get(entry=entry).scene_id, scene.pk)
        self.assertEqual(PlotLoreLink.objects.get(entry=entry).thread_id, plot.pk)
        entry.refresh_from_db()
        self.assertEqual((entry.status, entry.kind), ("submitted", "rumor"))

    def test_lore_sharing_uses_host_character_identity_and_preserves_acquisition_source(self):
        from evennia_lore.models import LoreAcquisition, LoreEntry

        entry = LoreEntry.create_entry("Syntax sharing", self.char1, body="A shared account.")
        entry.publish(reviewed_by=self.char1)
        command = self.command("+share")
        self.call(command, f"Char2=#{entry.entry_number}")
        self.assertFalse(LoreAcquisition.objects.filter(entry=entry).exists())
        self.expect(command, f"#{entry.entry_number}=Char2", "Shared")
        acquisition = LoreAcquisition.objects.get(entry=entry, character=self.char2)
        self.assertEqual((acquisition.source, acquisition.shared_by_id), ("shared", self.char1.pk))

    def test_thread_companion_preserves_host_permissions_and_sealed_answers(self):
        from evennia_plots.models import PlotThread, StoryThread

        plot = PlotThread.create_thread(name="Syntax plot", creator=self.char2)
        plot.activate()
        command = self.command("+thread")
        self.expect(
            command, f"/new #{plot.plot_number}=An open question", "Added thread", caller=self.char2
        )
        thread = plot.story_threads.get()
        self.expect(command, f"/seal {thread.ref}=Hidden answer", "Sealed", caller=self.char2)
        self.assertNotIn("Hidden answer", self.call(command, thread.ref, caller=self.char2))
        self.call(command, f"/resolve/reveal {thread.ref}=Solved", caller=self.char2)
        thread.refresh_from_db()
        self.assertEqual(thread.status, StoryThread.Status.OPEN)
        self.assertFalse(thread.sealed_answer_revealed)
        self.call(command, f"/resolve {thread.ref}=Solved", caller=self.char2)
        self.assertNotIn("Hidden answer", self.call(command, thread.ref, caller=self.char2))
        self.call(command, f"/reveal {thread.ref}", caller=self.char2)
        self.assertIn("Hidden answer", self.call(command, thread.ref, caller=self.char2))

    def test_flat_plot_links_use_real_scene_board_and_calendar_partners(self):
        from django.utils import timezone
        from evennia_boards.models import Board, Post
        from evennia_calendar.models import CalendarEvent
        from evennia_plots.models import PlotBoardLink, PlotCalendarLink, PlotThread, ScenePlotLink
        from evennia_scenes.models import Scene

        plot = PlotThread.create_thread(name="Syntax links", creator=self.char2)
        plot.activate()
        scene = Scene.objects.create(title="Linked scene", room=self.room1, creator=self.char2)
        board = Board.objects.create(name="Syntax board")
        post = Post.create_post(board=board, author=self.char2, title="Report", content="News")
        event = CalendarEvent.create_event(
            creator=self.char2, title="Syntax event", scheduled_time=timezone.now()
        )
        command = self.command("+plot")
        for switch, value, model in (
            ("scene", str(scene.pk), ScenePlotLink),
            ("post", f"{board.name}/{post.post_number}", PlotBoardLink),
            ("event", str(event.pk), PlotCalendarLink),
        ):
            self.call(command, f"/link/{switch} #{plot.plot_number}={value}", caller=self.char2)
            self.assertFalse(model.objects.filter(thread=plot).exists())
            self.expect(
                command, f"/{switch} #{plot.plot_number}={value}", "Linked", caller=self.char2
            )
            self.assertEqual(model.objects.filter(thread=plot).count(), 1)

    def test_cluster_companion_seating_enters_the_personal_calendar(self):
        import datetime
        import random

        from django.utils import timezone
        from evennia_calendar.models import RSVP, CalendarEvent, ClusterRSVP, EventCluster
        from evennia_calendar.scheduler import run_cluster_lottery

        cluster_command = self.command("+cluster")
        self.call(cluster_command, "/new Syntax calendar cluster")
        cluster = EventCluster.objects.get(title="Syntax calendar cluster")
        event = CalendarEvent.create_event(
            creator=self.char1,
            title="Syntax seating",
            scheduled_time=timezone.now() + datetime.timedelta(days=7),
            is_staff_event=True,
            participant_cap=2,
        )
        self.call(cluster_command, f"/add {event.pk}={cluster.pk}")
        self.call(cluster_command, f"/lock {cluster.pk}")
        self.call(cluster_command, f"/rank {cluster.pk}={event.pk}", caller=self.char2)
        self.assertTrue(ClusterRSVP.objects.filter(character=self.char2, status="pending").exists())
        self.assertFalse(RSVP.objects.filter(character=self.char2).exists())
        self.assertNotIn(
            "Syntax seating", self.call(self.command("+calendar"), "/mine", caller=self.char2)
        )
        cluster.refresh_from_db()
        run_cluster_lottery(cluster, rng=random.Random(19))
        self.expect(self.command("+calendar"), "/mine", "Lottery Selected", caller=self.char2)
        self.expect(cluster_command, f"/mine {cluster.pk}", "Assigned event", caller=self.char2)
        self.call(self.command("+rsvp"), f"/confirm {event.pk}", caller=self.char2)
        self.expect(self.command("+calendar"), "/mine", "Confirmed", caller=self.char2)

    def test_challenge_companion_and_npc_aware_tests_keep_scene_privacy(self):
        from unittest.mock import patch

        from evennia_rp_chargen.models import CharacterBuild
        from evennia_rp_chargen.stats import StatHandler
        from evennia_rp_contest.models import Challenge, CheckRecord
        from evennia_scenes.models import LogEntry, Scene

        from evennia_rp_rules.dice import ScriptedRoller
        from evennia_rp_rules.ruleset import get_ruleset

        CharacterBuild.objects.create(character=self.char2)
        stats = StatHandler(self.char2)
        for key in get_ruleset().stats:
            stats.set(key, get_ruleset().parse_rating("B"))
        build = CharacterBuild.objects.get(character=self.char2)
        build.status = "finalized"
        build.save(update_fields=["status"])
        scene = Scene.objects.create(room=self.room1, room_name=self.room1.key)
        self.room1.active_scene_id = scene.pk
        challenge = self.command("+challenge")
        self.expect(challenge, "/new A=Hold the audience", "challenge #1", caller=self.char2)
        self.expect(challenge, "/suggest #1=Presence/Performance", "edits", caller=self.char2)
        self.expect(challenge, "/difficulty #1=B", "edits", caller=self.char2)
        self.expect(challenge, "/once #1", "once", caller=self.char2)
        with patch("evennia_rp_rules.pipeline.default_roller", return_value=ScriptedRoller([0])):
            self.expect(
                self.command("+test"),
                "#1=Presence/Performance # At #12 ~ = {actor}",
                "tests Presence",
                caller=self.char2,
            )
        record = CheckRecord.objects.get()
        self.assertEqual(record.challenge_id, Challenge.objects.get().pk)
        self.assertEqual(record.comment, "At #12 ~ = {actor}")
        log = LogEntry.objects.get(scene=scene)
        self.assertIn(record.comment, log.content)
        self.assertNotIn("roll", log.content)
        self.assertNotIn("vs B", log.content)
        self.expect(challenge, f"/void #1.{record.pk} # Agreed", "voids", caller=self.char2)
        self.expect(challenge, "/history #1", "[VOID: Agreed]", caller=self.char2)
        self.expect(challenge, "/review #1", "Only staff", caller=self.char2)
        self.expect(challenge, "/review #1", '"roll"', caller=self.char1)
        self.expect(
            self.command("+test"), "/set B~Retired", "Unknown or ambiguous", caller=self.char2
        )
        self.assertEqual(Challenge.objects.count(), 1)
        self.assertEqual(CheckRecord.objects.count(), 1)
