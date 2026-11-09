# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Links presentation provider for Social's shared ignore service."""

from evennia_links.ignoring import ignore_mode_requested
from evennia_social import ignore


def provide(sender, viewer, sender_object, kind, **kwargs):
    """Answer board and channel presentation from the same boundary service.

    ``channels`` is ordinary OOC delivery; ``ic_channels`` uses character
    post levels. Both channel kinds share the ``channels`` preference.
    """
    if kind not in ("boards", "channels", "ic_channels", "notices"):
        return None
    if not (getattr(viewer, "account", None) or hasattr(viewer, "db")):
        return None
    account = ignore.account_for(viewer)
    if not account or account.is_superuser or account.check_permstring("Builder"):
        return None
    if kind == "notices":
        cache = kwargs.get("notice_cache")
        if cache is None:
            return "hide" if ignore.blocks_channel(viewer, sender_object) else None
        if "evennia_social.boundaries" not in cache:
            named, old = ignore.entries(account), ignore.earlier(account)
            owners = {}
            if named or old:
                from evennia_links.characters import playable_accounts

                for account_id, characters in playable_accounts():
                    for character in characters:
                        owners.setdefault(character.pk, set()).add(account_id)
            cache["evennia_social.boundaries"] = (named, old, owners, {})
        named, old, owners, staff = cache["evennia_social.boundaries"]
        from evennia.accounts.models import AccountDB

        ids = (
            {sender_object.pk}
            if isinstance(sender_object, AccountDB)
            else set(owners.get(getattr(sender_object, "pk", None), set()))
        )
        # Match ignore.owners() without repeating its whole-roster sweep.
        if owner := ignore.account_for(sender_object):
            ids.add(owner.pk)
        covered = bool(ids & old) or any(
            ids.intersection(entry["accounts"]) for entry in named.values()
        )
        key = tuple(sorted(ids))
        if covered and key not in staff:
            staff[key] = ignore._staff(ids)
        return "hide" if covered and not staff[key] else None
    hidden = (
        ignore.blocks_channel(viewer, sender_object)
        if kind == "channels"
        else ignore.ignore_level(viewer, sender_object) == ignore.HIDDEN
    )
    if hidden:
        preference = (
            ignore.boards_preference(account)
            if kind == "boards"
            else ignore.channels_preference(account)
        )
        if preference == ignore.HIDE:
            return "hide"
        return "placeholder"
    return None


def register():
    """Install the provider once even if app readiness is invoked repeatedly."""
    ignore_mode_requested.connect(provide, dispatch_uid="evennia_social.ignore_mode")
