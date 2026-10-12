# SPDX-License-Identifier: BSD-3-Clause
"""Disposable guests and the boundary around a host's trial area.

Rooms in the trial area carry ``wing`` in tag category ``guest``. One also
carries ``start``. Add GuestCharacterMixin before other character mixins and
GuestAccountMixin before DefaultGuest. Configure GUEST_CHARACTER_CMDSET and
GUEST_ACCOUNT_CMDSET with the host's restricted command sets.
"""

from django.conf import settings


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
    from evennia_links.characters import account_ids

    return any(is_guest(owner) for owner in AccountDB.objects.filter(pk__in=account_ids(obj)))


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
        try:
            start = guest_start()
        except ValueError as exc:
            return None, [str(exc)]
        kwargs.update(location=start, home=start)
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
        self.msg(
            "Welcome, guest. Use guest <message> to chat, +stats to try a sheet, "
            "and +stats/reset to start again. Pages may be sent to staff only."
        )
