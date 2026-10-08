"""Real sandbox seams, runnable after physically uninstalling RP partners."""

from importlib import import_module
from unittest import mock

from django.apps import apps
from django.core.management import call_command
from django.test import RequestFactory, override_settings
from evennia.utils.search import search_object
from evennia.utils.test_resources import EvenniaTest
from typeclasses.characters import Character
from typeclasses.rooms import Room

from evennia_rp_rules.dice import ScriptedRoller
from evennia_rp_rules.subjects import DictStatSource, get_subject
from world.sandbox import content, glue


def scaled_plot_xp(source, **context):
    from decimal import Decimal

    from evennia_plots.integrations.gating import resolve_xp_multiplier

    return Decimal("2") * resolve_xp_multiplier(source, **context)


class TestConfiguredPlotXP(EvenniaTest):
    @override_settings(XP_MULTIPLIER_RESOLVER="world.sandbox.test_rp_partners.scaled_plot_xp")
    def test_real_plot_collector_uses_host_policy_and_thread_arc(self):
        if not apps.is_installed("evennia_xp"):
            self.skipTest("requires XP partner")
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone
        from evennia_plots.integrations.xp import collect_thread_bonuses
        from evennia_plots.models import PlotArc, PlotParticipant, PlotThread

        arc = PlotArc.create_arc(name="Host policy", creator=self.char1)
        arc.xp_mult_thread_bonus = Decimal("0.5")
        arc.save(update_fields=["xp_mult_thread_bonus"])
        thread = PlotThread.create_thread(name="Collector seam", creator=self.char1)
        thread.arc = arc
        thread.status = PlotThread.Status.CONCLUDED
        thread.bonus_xp_computed = 3
        thread.concluded_at = timezone.now()
        thread.save()
        PlotParticipant.objects.create(thread=thread, character=self.char1)
        awards = list(collect_thread_bonuses(timezone.now() + timedelta(hours=1)))
        self.assertEqual(len(awards), 1)
        self.assertEqual(awards[0].amount, Decimal("3"))
        self.assertEqual(awards[0].multiplier, Decimal("1"))


class RPSeedMixin:
    character_typeclass = Character
    room_typeclass = Room

    def setUp(self):
        super().setUp()
        origin = self.settings(START_LOCATION=f"#{self.room1.id}")
        origin.enable()
        self.addCleanup(origin.disable)
        if apps.is_installed("evennia_rptracker"):
            from evennia_rptracker.tracker import _active_sessions

            _active_sessions.clear()
            self.addCleanup(_active_sessions.clear)
        call_command("seed_sandbox", verbosity=0)
        self.grounds = search_object("Proving Grounds")[0]
        self.dummy = search_object(content.RP_DUMMY_NAME)[0]
        self.samples = [search_object(name)[0] for name in content.SCENE_SPEAKERS]


class TestRPPartners(RPSeedMixin, EvenniaTest):
    def test_stat_block_fallback_without_creating_a_sheet(self):
        subject = get_subject(self.dummy)
        self.assertIsInstance(subject, DictStatSource)
        self.assertEqual(subject.get_rating("intellect").display(), "C")
        if apps.is_installed("evennia_rp_chargen"):
            from evennia_rp_chargen.models import CharacterBuild

            self.assertFalse(CharacterBuild.objects.filter(character=self.dummy).exists())

    def test_runtime_vocabulary_or_ruleset_fallback(self):
        vocabulary = glue.rp_vocabulary()
        self.assertIsNotNone(vocabulary.find("Ritual", kind="domain"))
        self.assertIsNotNone(vocabulary.find("Blades", kind="style"))

    def test_allowance_then_real_xp_or_unavailable_partner(self):
        if not apps.is_installed("evennia_rp_chargen"):
            return
        from evennia_rp_chargen import abilities
        from evennia_rp_chargen.models import AbilityTransaction, CharacterBuild
        from evennia_rp_chargen.services import ChargenError

        sample = self.samples[0]
        abilities.set_allowance(sample, 1)
        if apps.is_installed("evennia_xp"):
            from evennia_xp.awards import record_xp
            from evennia_xp.models import CharacterXP, XPLog, XPSpend

            record_xp(sample.pk, 10, XPLog.SourceType.MANUAL_GRANT, 0)
            _copy, paid = abilities.acquire(sample, "combat-focus", "blades")
            self.assertEqual((paid.allowance, paid.xp), (1, 2))
            self.assertEqual(
                XPSpend.objects.get().ref_key,
                AbilityTransaction.objects.get(ledger_ref__gt="").ledger_ref,
            )
            self.assertEqual(CharacterXP.objects.get(character_id=sample.pk).total_earned, 10)
            self.assertEqual(abilities.balance(sample), (0, 8))
            # Upgrades compound (2, then 4), entirely from earned XP here.
            abilities.upgrade(sample, "combat-focus", "blades")
            abilities.upgrade(sample, "combat-focus", "blades")
            with self.assertRaises(ChargenError):
                abilities.upgrade(sample, "combat-focus", "blades")
            self.assertEqual(abilities.find_owned(sample, "combat-focus", "blades").level, 3)
            self.assertEqual(XPSpend.objects.count(), 3)
            _, returned, kept = abilities.revoke(sample, "combat-focus", "blades", refund=True)
            self.assertEqual((returned.allowance, returned.xp, kept), (1, 8, 0))
            self.assertEqual(abilities.balance(sample), (1, 10))
            self.assertEqual(XPSpend.objects.filter(refunded_at__isnull=False).count(), 3)
        else:
            self.assertEqual(abilities.balance(sample), (1, None))
            before = AbilityTransaction.objects.count()
            with self.assertRaisesMessage(ChargenError, "XP spending isn't available"):
                abilities.acquire(sample, "combat-focus", "blades")
            self.assertEqual(AbilityTransaction.objects.count(), before)
            self.assertEqual(CharacterBuild.objects.get(character=sample).allowance_spent, 0)

    def test_commands_follow_installed_apps(self):
        from evennia.commands.command import CMD_IGNORE_PREFIXES

        self.char2.cmdset.update()
        commands = list(self.char2.cmdset.current)
        for label, keys in (
            ("evennia_rp_contest", ("test",)),
            (
                "evennia_rp_chargen",
                (
                    "sheet",
                    "stats",
                    "pips",
                    "abilities",
                    "lock",
                    "unlock",
                    "spend",
                    "upgrade",
                    "chargen",
                ),
            ),
            ("evennia_scenes", ("scene", "log")),
            ("evennia_rptracker", ("activity",)),
            ("evennia_xp", ("xp",)),
        ):
            modules = {f"{label}.commands"}
            names = {
                command.key.lstrip(CMD_IGNORE_PREFIXES)
                for command in commands
                if type(command).__module__ in modules
            }
            for key in keys:
                self.assertEqual(key in names, apps.is_installed(label), (label, key))

    def test_actual_pose_and_disconnect_hooks(self):
        sample = self.samples[0]
        sample.record_pose("waves to the playtesters.", pose_type="pose")
        if apps.is_installed("evennia_rp_chargen"):
            from evennia_rp_chargen import locks

            self.assertTrue(locks.is_locked(sample))
        sample.at_post_unpuppet()

    def test_dummy_can_resolve_a_real_test(self):
        if not apps.is_installed("evennia_rp_contest"):
            return
        from evennia_rp_contest import services
        from evennia_rp_contest.parsing import parse_test

        record = services.perform_test(
            self.dummy, parse_test("#2=Intellect/Blades"), roller=ScriptedRoller([0])
        )
        self.assertEqual(record.challenge.number, 2)
        self.assertEqual(record.rating_display, "C")
        self.assertIsNone(record.scene_id)

    def test_rendered_home_page_and_urls(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import override_settings
        from django.urls import reverse
        from web.website.views.index import SandboxIndexView

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        with override_settings(ROOT_URLCONF="web.urls"):
            self.assertEqual(reverse("index"), "/")
            response = SandboxIndexView.as_view()(request)
            response.render()
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for label in ("evennia_rp_rules", "evennia_rp_chargen", "evennia_rp_contest"):
            self.assertEqual(label in html, apps.is_installed(label))

    def test_start_and_stop_with_real_installed_partners(self):
        from django.conf import settings
        from django.utils.module_loading import import_string

        for _category, collector in settings.XP_COLLECTORS:
            self.assertTrue(callable(import_string(collector)))
        for hook in [*settings.XP_ANTIGAMING_SWEEPS, *settings.XP_POST_BATCH_HOOKS]:
            self.assertTrue(callable(import_string(hook)))
        hooks = import_module("server.conf.at_server_startstop")
        # Keep the real import/registry path; don't start persistent timers in a test.
        with mock.patch("evennia_calendar.scheduler.ensure_calendar_script_running"):
            hooks.at_server_start()
            hooks.at_server_stop()


class TestLoginXPSummary(EvenniaTest):
    """The first-login summary through the game's real puppet hook.

    Lives here so the absent-partner run covers it too: without evennia_xp the
    hook must still complete quietly.
    """

    character_typeclass = Character
    room_typeclass = Room

    def test_summary_once_per_batch_or_quiet_without_xp(self):
        if apps.is_installed("evennia_xp"):
            from evennia_xp.awards import record_xp
            from evennia_xp.models import XPLog

            record_xp(self.char1.pk, 2, XPLog.SourceType.RP_SESSION, 501, week="2026-W40")
        with mock.patch.object(self.char1, "msg") as message:
            self.char1.at_post_puppet()
            self.char1.at_post_puppet()
        summaries = [
            call.args[0] for call in message.call_args_list if "XP awarded for week" in call.args[0]
        ]
        if apps.is_installed("evennia_xp"):
            self.assertEqual(len(summaries), 1)
            self.assertIn("2026-W40", summaries[0])
        else:
            self.assertEqual(summaries, [])
        self.assertIsNotNone(self.char1.attributes.get("sandbox_last_seen"))


class TestActivityXPProjection(EvenniaTest):
    """+activity through the game's cmdset, with evennia_xp's projection hook.

    With xp installed, a lore entry published this week shows as pending XP;
    with xp absent, the hook is unset and +activity still runs.
    """

    character_typeclass = Character
    room_typeclass = Room

    def run_activity(self):
        from commands.default_cmdsets import CharacterCmdSet

        command = next(c for c in CharacterCmdSet().commands if c.key == "+activity")
        command.caller = self.char1
        command.switches = []
        command.args = ""
        with mock.patch.object(self.char1, "msg") as replies:
            command.func()
        return " ".join(str(call.args[0]) for call in replies.call_args_list if call.args)

    def test_projected_xp_or_plain_activity_without_xp(self):
        if not apps.is_installed("evennia_rptracker"):
            return
        from evennia_lore.models import LoreEntry

        LoreEntry.create_entry(title="Tide tables", author=self.char1)
        output = self.run_activity()
        self.assertIn("Your RP Activity", output)
        if apps.is_installed("evennia_xp"):
            self.assertIn("Lore Authored +1.00", output)
        else:
            self.assertNotIn("Projected XP", output)


class TestRoomMoodSceneRights(EvenniaTest):
    """+mood through the game's own cmdset, Room typeclass and scenes partner.

    char2 is an ordinary player. With evennia_scenes installed, joining a
    public scene in the room is what lets them set the mood; with it absent,
    the same player is refused and the command still works for staff.
    """

    character_typeclass = Character
    room_typeclass = Room

    def mood_command(self):
        from commands.default_cmdsets import CharacterCmdSet

        return next(c for c in CharacterCmdSet().commands if c.key == "+mood")

    def run_mood(self, caller, args):
        command = self.mood_command()
        command.caller = caller
        command.switches = []
        command.args = args
        with mock.patch.object(caller, "msg") as replies:
            command.func()
        return " ".join(str(call.args[0]) for call in replies.call_args_list if call.args)

    def test_scene_participant_or_refused_without_scenes(self):
        if apps.is_installed("evennia_scenes"):
            from evennia_scenes.models import Scene, SceneParticipant

            scene = Scene.objects.create(
                title="Mood check",
                room=self.room1,
                room_name=self.room1.key,
                creator=self.char1,
                creator_name=self.char1.key,
                privacy=Scene.Privacy.PUBLIC,
            )
            SceneParticipant.objects.create(
                scene=scene, character=self.char2, character_name=self.char2.key
            )
            self.assertIn("Mood set", self.run_mood(self.char2, "Thunder rolls in."))
            self.assertIn("Thunder rolls in.", self.room1.return_appearance(self.char1))
        else:
            self.assertIn("can't set the mood", self.run_mood(self.char2, "Thunder rolls in."))
            self.assertIn("Mood set", self.run_mood(self.char1, "Thunder rolls in."))
            self.assertIn("Thunder rolls in.", self.room1.return_appearance(self.char2))
