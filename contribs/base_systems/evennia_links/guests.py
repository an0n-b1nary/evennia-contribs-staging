# SPDX-License-Identifier: BSD-3-Clause
"""Disposable guests and the boundary around a host's trial area.

Rooms in the trial area carry ``wing`` in tag category ``guest``. One also
carries ``start``. Add GuestCharacterMixin before other character mixins and
GuestAccountMixin before DefaultGuest. Configure GUEST_CHARACTER_CMDSET and
GUEST_ACCOUNT_CMDSET with the host's restricted command sets.
"""

from django.conf import settings

from .identity import is_visitor  # noqa: F401 — public re-export


def is_guest(obj):
    """Recognize actual guest accounts, including their offline characters.

    Hierarchical ``perm(Guests)`` also matches ordinary Players. Identity
    comes from the guest account typeclass, never that permission check.
    """
    if obj is None:
        return False
    from django.core.exceptions import ObjectDoesNotExist
    from evennia.accounts.accounts import DefaultGuest
    from evennia.accounts.models import AccountDB
    from evennia.objects.models import ObjectDB

    if isinstance(obj, AccountDB):
        return isinstance(obj, DefaultGuest)
    if not isinstance(obj, ObjectDB):
        return False
    tags = getattr(obj, "tags", None)
    if tags is None:
        return False
    if tags.has("character", category="guest"):
        return True
    try:
        account = getattr(obj, "account", None)
    except ObjectDoesNotExist:
        # Evennia may retain an instance's pk after deleting its database row.
        return False
    if account is not None and is_guest(account):
        return True
    # Sweep only guest accounts' rosters: a full account_ids() sweep here would
    # turn every playable_characters() pass into one sweep per character.
    paths = _guest_typeclass_paths()
    if not paths:
        return False
    from evennia_links.characters import playable_accounts

    guests = AccountDB.objects.filter(db_typeclass_path__in=paths)
    return any(
        obj.pk in {character.pk for character in characters}
        for _, characters in playable_accounts(guests)
    )


def _guest_typeclass_paths():
    """Stored account typeclass paths that resolve to a DefaultGuest subclass."""
    from evennia.accounts.accounts import DefaultGuest
    from evennia.accounts.models import AccountDB
    from evennia.utils.utils import class_from_module

    guest_paths = []
    for path in AccountDB.objects.order_by().values_list("db_typeclass_path", flat=True).distinct():
        try:
            typeclass = class_from_module(path)
        except ImportError:
            continue
        if isinstance(typeclass, type) and issubclass(typeclass, DefaultGuest):
            guest_paths.append(path)
    return guest_paths


def in_guest_wing(room):
    return bool(room and room.tags.has("wing", category="guest"))


def guest_start():
    """Resolve a unique seeded start room; fail closed before seed is ready."""
    from evennia.utils.search import search_tag

    rooms = list(search_tag("start", category="guest"))
    if len(rooms) != 1 or not in_guest_wing(rooms[0]):
        raise ValueError("The guest wing is unavailable. Please contact staff.")
    return rooms[0]


class GuestCharacterMixin:
    """Enforce the guest boundary on exits and direct command-driven moves."""

    def get_cmdsets(self, caller, current, **kwargs):
        current, cmdsets = super().get_cmdsets(caller, current, **kwargs)
        # Unrestricted discovery already gathers exits; adding them again would
        # duplicate every exit command (exit cmdsets merge with duplicates).
        if current.no_exits or not current.no_objs or not self.location or not is_guest(self):
            return current, cmdsets
        from evennia.objects.objects import DefaultExit, ExitCommand

        # Evennia's no_objs also suppresses automatic exit discovery. Supply
        # only stock traversal commands, retaining the host's object allowlist.
        cmdsets = list(cmdsets)
        for exit_obj in self.location.exits:
            if not isinstance(exit_obj, DefaultExit) or not exit_obj.access(
                caller, "call", no_superuser_bypass=True
            ):
                continue
            DefaultExit.at_cmdset_get(exit_obj, caller=caller)
            for candidate in exit_obj.cmdset.cmdset_stack:
                if candidate.key == "ExitCmdSet" and all(
                    type(command) is ExitCommand and command.obj == exit_obj
                    for command in candidate.commands
                ):
                    cmdsets.append(candidate)
        return current, cmdsets

    def move_to(self, destination, *args, **kwargs):
        # Even privileged commands may request move_hooks=False. The boundary
        # remains a rule of this character, rather than an optional move hook.
        target = getattr(destination, "destination", None) or destination
        if is_guest(self) and not in_guest_wing(target):
            self.msg("Guests must stay in the guest wing.")
            return False
        return super().move_to(destination, *args, **kwargs)

    def at_pre_move(self, destination, **kwargs):
        if is_guest(self) and not in_guest_wing(destination):
            self.msg("Guests must stay in the guest wing.")
            return False
        return super().at_pre_move(destination, **kwargs)

    def at_pre_object_receive(self, arriving_object, source_location, **kwargs):
        # Other players cannot give a guest durable inventory either.
        if is_guest(self):
            arriving_object.msg("Guests cannot receive items.")
            return False
        return super().at_pre_object_receive(arriving_object, source_location, **kwargs)


class GuestAccountMixin:
    """Seeded guest arrival, restricted commands, and a single guest channel."""

    # Hosts override this to name their own guest commands.
    guest_welcome = "Welcome, guest. Pages may be sent to staff only."

    @classmethod
    def authenticate(cls, **kwargs):
        if settings.GUEST_ENABLED:
            try:
                guest_start()
            except ValueError as exc:
                return None, [str(exc)]
        account, errors = super().authenticate(**kwargs)
        if account and errors:
            account.delete()
            return None, errors
        return account, errors

    def get_display_name(self, looker=None, **kwargs):
        return super().get_display_name(looker, **kwargs) + " (guest)"

    def basetype_setup(self):
        super().basetype_setup()
        self.cmdset.add(settings.GUEST_ACCOUNT_CMDSET, persistent=True)

    def create_character(self, *args, **kwargs):
        from .guest_names import guest_character_name

        try:
            start = guest_start()
        except ValueError as exc:
            return None, [str(exc)]
        try:
            key = guest_character_name()
        except Exception:
            # Raising here would skip authenticate()'s cleanup and strand the
            # new guest account, consuming its GUEST_LIST name for good.
            from evennia.utils import logger

            logger.log_trace("Cannot name a guest character.")
            return None, ["Guest characters are unavailable. Please contact staff."]
        kwargs.update(key=key, location=start, home=start)
        character, errors = super().create_character(*args, **kwargs)
        if character:
            character.tags.add("character", category="guest")
            character.cmdset.add(settings.GUEST_CHARACTER_CMDSET, persistent=True)
        return character, errors

    def at_post_login(self, session=None, **kwargs):
        from evennia.comms.models import ChannelDB

        # Account creation may subscribe to DEFAULT_CHANNELS before this hook.
        for channel in ChannelDB.objects.get_subscriptions(self):
            channel.disconnect(self)
        channels = list(ChannelDB.objects.get_by_tag("chat", category="guest"))
        if len(channels) != 1:
            self.msg("The guest channel is unavailable. Please contact staff.")
        else:
            channels[0].connect(self)
        super().at_post_login(session=session, **kwargs)
        self.msg(self.guest_welcome)
