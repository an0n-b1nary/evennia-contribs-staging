# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Communication identity policy, independent of record ownership.

Typeclasses are imported inside the check, after Django's app registry is
ready. Importing this module from an AppConfig must not load Evennia models.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def comms_identity():
    """Return the host's validated communication mode (default: account)."""
    mode = getattr(settings, "EVENNIA_COMMS_IDENTITY", "account")
    if mode not in ("account", "character"):
        raise ImproperlyConfigured('EVENNIA_COMMS_IDENTITY must be "account" or "character".')
    return mode


def _is_staff(actor):
    if actor is None:
        return False
    account = getattr(actor, "account", None) or actor
    permission_check = getattr(account, "check_permstring", None)
    return bool(
        getattr(account, "is_superuser", False)
        or (permission_check and permission_check("Builder"))
    )


def is_visitor(actor, session=None):
    """Guests, plus non-staff accounts without a puppet in character mode.

    Supplying a session makes the decision local to that session. Without
    one, any active puppet makes an account a non-visitor; resolving ambiguous
    senders remains the channel layer's responsibility.
    """
    from evennia.accounts.models import AccountDB

    from .guests import is_guest

    if actor is None:
        return False
    if is_guest(actor):
        return True
    if comms_identity() == "account" or not isinstance(actor, AccountDB) or _is_staff(actor):
        return False
    if session is not None:
        return actor.get_puppet(session) is None
    return not actor.get_all_puppets()


class CharacterCommsAccountMixin:
    """Mask account names from other players, including anonymous histories.

    Put this FIRST, before ModerationAccountMixin, GuestAccountMixin and the
    Evennia account class. Staff, the account itself and its characters retain
    the cooperative display name (including a guest suffix when applicable).
    """

    comms_identity = "character"

    def get_display_name(self, looker=None, **kwargs):
        if (
            looker == self
            or _is_staff(looker)
            or (looker is not None and getattr(looker, "account", None) == self)
            # Read the roster directly: characters.all() rewrites the attribute
            # on every call, and strangers reach this test on every message.
            or (looker is not None and looker in (self.db._playable_characters or ()))
        ):
            return super().get_display_name(looker, **kwargs)
        return "Newcomer"


def check_comms_identity():
    """Refuse mode-specific classes wired under the wrong communication mode.

    Call from the host's ``at_server_start`` as well as Django system checks.
    Channel implementations opt in with the ``comms_identity`` class marker;
    character mode requires a character-marked channel and the account display
    mixin on both account typeclasses. Unmarked commands work in either mode.
    """
    from evennia.utils.utils import class_from_module

    mode = comms_identity()
    problems = []

    def inspect(cls, source):
        # Inspect bases too: a subclass must not hide a conflicting mixin by
        # overriding its marker or adding another mode-specific mixin first.
        for base in cls.__mro__:
            marker = base.__dict__.get("comms_identity")
            if marker is not None and marker != mode:
                problems.append(
                    f"{source}: {base.__module__}.{base.__qualname__} requires {marker!r} mode"
                )

    def resolve(setting_name, search_paths, required=True):
        # Evennia accepts paths relative to TYPECLASS_PATHS and CMDSET_PATHS.
        path = getattr(settings, setting_name, None)
        if not path:
            if required:
                problems.append(f"{setting_name}: a class path is required")
            return None
        try:
            cls = class_from_module(path, defaultpaths=getattr(settings, search_paths, None))
            if not isinstance(cls, type):
                raise TypeError("expected a class")
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            problems.append(f"{setting_name}: cannot load {path!r}: {exc}")
            return None
        inspect(cls, setting_name)
        return cls

    for name in ("BASE_ACCOUNT_TYPECLASS", "BASE_GUEST_TYPECLASS", "BASE_CHANNEL_TYPECLASS"):
        cls = resolve(name, "TYPECLASS_PATHS")
        if mode != "character":
            continue
        if name == "BASE_CHANNEL_TYPECLASS":
            if cls is None or getattr(cls, "comms_identity", None) != "character":
                problems.append(f"{name} requires CharacterCommsChannelMixin (character marker)")
        elif cls is None or not issubclass(cls, CharacterCommsAccountMixin):
            problems.append(f"{name} requires CharacterCommsAccountMixin first in its MRO")
        else:
            # Host subclasses may inherit an already correctly composed class.
            for base in cls.__mro__[1:]:
                if base is CharacterCommsAccountMixin:
                    break
                if "get_display_name" in base.__dict__:
                    problems.append(
                        f"{name}: CharacterCommsAccountMixin must precede {base.__name__}"
                    )
                    break

    for name in (
        "CMDSET_ACCOUNT",
        "CMDSET_CHARACTER",
        "GUEST_ACCOUNT_CMDSET",
        "GUEST_CHARACTER_CMDSET",
    ):
        cls = resolve(name, "CMDSET_PATHS", required=not name.startswith("GUEST_"))
        if cls is None:
            continue
        try:
            cmdset = cls()
        except Exception as exc:
            problems.append(f"{name}: cannot instantiate {cls.__name__}: {exc}")
            continue
        for command in cmdset.commands:
            inspect(type(command), name)

    if problems:
        raise ImproperlyConfigured(
            f"Communication identity configuration ({mode}):\n" + "\n".join(dict.fromkeys(problems))
        )


def comms_identity_system_check(app_configs=None, **kwargs):
    """Django adapter; register at ready(), resolve classes only when called."""
    from django.core.checks import Error

    try:
        check_comms_identity()
    except ImproperlyConfigured as exc:
        return [Error(str(exc), id="evennia_links.E001")]
    return []
