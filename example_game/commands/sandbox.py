"""
Self-service sandbox controls for the demo game.

Demo-only glue, and deliberately here rather than in any contrib: no real
game lets a player hand themselves Builder.

Why a toggle instead of simply making every playtester a Builder - all ten
installed contribs default their staff lock to ``perm(Builder)`` (see the
``*_STAFF_LOCK`` block in server/conf/settings.py), so one blanket promotion
would erase the entire player half of the demo at once: the lore approval
queue seen from the submitting side, the anonymised job submitter, read-only
boards, the +plot/+arc split. A toggle shows both halves, which is more
feature surface, not less.
"""

from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils import logger

BUILDER_PERM = "Builder"

# Deliberately *above* what +sandbox/builder hands out. Gating the reset on
# Builder would be no gate at all here, since anyone can become a Builder on
# request - and a reset deletes every seeded room out from under whoever is
# standing in one.
RESET_LOCK = "perm(Admin)"


def _stray_rooms():
    """Rooms a reset will leave behind.

    seed_sandbox purges Evennia objects by tag, so any room a playtester dug
    by hand is untagged and survives. Reporting the count is the honest way to
    present that: the gap is visible instead of surprising.

    The origin room is excluded because it is untagged *by design* - it is the
    permanent room at START_LOCATION that the seeder re-dresses rather than
    creates (seed_sandbox._origin_room). Counting it would put a floor of 1
    under a number that should read zero on an untouched sandbox.
    """
    from django.conf import settings
    from evennia.objects.models import ObjectDB
    from evennia.objects.objects import DefaultRoom
    from evennia.utils.search import search_tag

    # Imported lazily, and from the seeder rather than re-declared, so the tag
    # this counts against cannot drift from the tag the purge acts on.
    from world.sandbox.management.commands.seed_sandbox import (
        SANDBOX_TAG,
        SANDBOX_TAG_CATEGORY,
    )

    known = {obj.id for obj in search_tag(SANDBOX_TAG, category=SANDBOX_TAG_CATEGORY)}
    dbref = getattr(settings, "START_LOCATION", None)
    origin = ObjectDB.objects.get_id(dbref) if dbref else None
    if origin is not None:
        known.add(origin.id)
    return [room for room in DefaultRoom.objects.all_family() if room.id not in known]


class CmdSandbox(MuxCommand):
    """
    Sandbox controls: promote yourself, and rebuild the world.

    Usage:
        +sandbox                  - Status, and what each level unlocks
        +sandbox/builder on       - Grant yourself the Builder permission
        +sandbox/builder off      - Drop it again
        +sandbox/reset            - (Admin) Rebuild the seeded world

    Builder is a single switch for the whole game: every installed system
    gates its staff side on perm(Builder). Turning it on opens map and region
    editing, the lore approval queue, the job queue, board administration,
    plot arcs, scene management and XP awards - and closes the player-side
    view of those same systems, which is the half worth looking at first.

    With Builder on you can grow the map with no map command at all: `@dig
    north=Some Room` places the new room automatically. The exit's key or one
    of its aliases has to be a compass direction for that to fire, so `@dig
    gate=Some Room` digs the room but leaves it off the map. The `nexus` exit
    off the Sandbox Plaza is there to show exactly that.
    """

    key = "+sandbox"
    aliases = []  # noqa: RUF012
    help_category = "Sandbox"
    locks = "cmd:all()"

    def func(self):
        if not self.switches:
            self._do_status()
            return

        switch = self.switches[0].lower()
        if switch == "builder":
            self._do_builder()
        elif switch == "reset":
            self._do_reset()
        else:
            self.caller.msg(f"|rUnknown switch: /{switch}|n")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _permission_targets(self):
        """The objects a self-promotion has to write to.

        Both the account and the puppet, because Evennia's perm() lockfunc
        reads them differently: unquelled it uses the account's hierarchy
        position and ignores the puppet's entirely, but under `quell` it takes
        the *minimum* of the two. Writing only the account would leave the
        toggle inert for a quelled session - and quelling is the only way the
        superuser running this sandbox can see the player side at all, since a
        superuser otherwise bypasses every lock outright.
        """
        account = getattr(self.caller, "account", None)
        return [obj for obj in (account, self.caller) if obj is not None]

    def _has_builder(self):
        """True if the Builder permission is actually set on this account.

        Not a lock check: perm(Builder) also answers yes for an Admin, a
        Developer, or a superuser bypass, and this reports the state of the
        toggle rather than the outcome of a lock.
        """
        account = getattr(self.caller, "account", None)
        if account is None:
            return False
        return BUILDER_PERM.lower() in [perm.lower() for perm in account.permissions.all()]

    # ------------------------------------------------------------------
    # Switches
    # ------------------------------------------------------------------

    def _do_status(self):
        account = getattr(self.caller, "account", None)
        strays = len(_stray_rooms())

        state = "|gON|n" if self._has_builder() else "|xoff|n"
        lines = [
            "|wSandbox controls|n",
            f"  Builder mode: {state}   (|w+sandbox/builder on|n / |woff|n)",
        ]

        if account is not None and account.is_superuser:
            lines.append(
                "  |ySuperuser: you bypass every lock.|n Turning Builder off will not show"
            )
            lines.append(
                "  you the player experience - type |wquell|n first, |wunquell|n to restore."
            )

        lines += [
            "",
            "Builder opens the staff half of every system at once: map and region",
            "editing, the lore approval queue, the job queue, board administration,",
            "plot arcs, scene management, XP awards. It also closes the player-side view",
            "of those same systems, so it is worth looking around before switching it on.",
            "",
            "|yKnown wart, not a bug:|n only |w+jobs|n, |w+discuss|n and |w+rptracker|n hide",
            "themselves from non-staff. Every other system lists its staff switches in",
            "|whelp|n for everyone and refuses them at execution.",
            "",
            "|w+sandbox/reset|n rebuilds the seeded world. Accounts, characters, and",
            "anything you dug yourself are left alone.",
            f"  Rooms made by hand, which a reset will not remove: |w{strays}|n",
        ]

        self.caller.msg("\n".join(lines))

    def _do_builder(self):
        arg = self.args.strip().lower()
        if arg not in ("on", "off"):
            self.caller.msg("|rUsage: +sandbox/builder on|n |ror|n |r+sandbox/builder off|n")
            return

        targets = self._permission_targets()
        if not targets:
            self.caller.msg("|rNo account is puppeting this object; nothing to promote.|n")
            return

        if arg == "on":
            for obj in targets:
                obj.permissions.add(BUILDER_PERM)
            self.caller.msg(
                "|gBuilder mode on.|n Try |w+map/check|n, |w+region/create|n, |w+jobs|n, or"
                " |w@dig north=A New Room|n to watch the map grow on its own."
            )
            return

        for obj in targets:
            obj.permissions.remove(BUILDER_PERM)
        self.caller.msg("|xBuilder mode off.|n You are back to the player view of every system.")
        if self.caller.locks.check_lockstring(self.caller, f"perm({BUILDER_PERM})"):
            # Dropping Builder cannot demote someone who outranks it, and a
            # superuser is not gated at all. Say so rather than let the toggle
            # look broken.
            self.caller.msg(
                "|yNote: you still pass perm(Builder) - through a higher permission"
                " (Admin, Developer) or through superuser bypass.|n"
            )

    def _do_reset(self):
        caller = self.caller
        if not caller.locks.check_lockstring(caller, RESET_LOCK):
            caller.msg(
                "|rOnly the sandbox's staff can reset the world.|n A reset deletes every"
                " seeded room, including one someone may be standing in, so it is held"
                " above the Builder permission |w+sandbox/builder|n hands out."
            )
            return

        from django.core.management import call_command

        caller.msg("Rebuilding the seeded world...")
        try:
            # In-process rather than a server restart: the seeder is content-only,
            # so accounts and characters ride through it untouched. verbosity=0
            # silences its stdout report, which would otherwise land in the server
            # log where the person who typed this cannot see it.
            call_command("seed_sandbox", verbosity=0)
        except Exception as err:
            logger.log_trace()
            caller.msg(f"|rReset failed: {err}|n Nothing further was changed.")
            return

        strays = len(_stray_rooms())
        caller.msg(
            "|gThe seeded world is rebuilt.|n Accounts and characters were not touched."
            " Anyone standing in a purged room was sent home to the Sandbox Plaza."
        )
        caller.msg(f"Rooms made by hand, left untouched by the purge: |w{strays}|n")
