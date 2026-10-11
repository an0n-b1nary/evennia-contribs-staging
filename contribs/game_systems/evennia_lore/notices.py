# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
OOC notices from lore to players and staff.

``notify(character, message)`` messages a character who is in the game now,
and otherwise keeps the message as a ``LoreNotice`` row until the character is
next puppeted. Delivery listens to Evennia's ``SIGNAL_OBJECT_POST_PUPPET``,
connected in ``LoreConfig.ready()``, so a game needs no typeclass wiring.

``file_staff_review(title, description)`` passes something staff should look
at to ``LORE_STAFF_REVIEW_HOOK``: a dotted path to ``callable(title,
description)``, such as evennia-jobs'
``evennia_jobs.integrations.staff_review.file_review_job``. Without the hook,
affirmation requests still wait in ``+lore/queue``.
"""

import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger("evennia")


def is_online(character):
    """Return True if *character* is puppeted by at least one session."""
    try:
        return bool(character.sessions.count())
    except Exception:
        return False


def notify(character, message, entry=None):
    """Tell *character* now if they're in the game, otherwise at next puppet.

    Args:
        character: ObjectDB character.
        message (str): The notice, already formatted.
        entry (LoreEntry, optional): The entry the notice is about.

    Returns:
        bool: True if delivered now, False if kept for later.
    """
    if character is None:
        return False
    if is_online(character):
        character.msg(message)
        return True
    from evennia_lore.models import LoreNotice

    LoreNotice.objects.create(character=character, entry=entry, message=message)
    return False


def deliver_pending(character):
    """Send *character* every notice kept for them, oldest first, then drop them.

    Returns:
        int: How many notices were delivered.
    """
    from evennia_lore.models import LoreNotice

    notices = list(LoreNotice.objects.filter(character=character).order_by("created_at", "pk"))
    if not notices:
        return 0
    character.msg("\n".join(notice.message for notice in notices))
    LoreNotice.objects.filter(pk__in=[notice.pk for notice in notices]).delete()
    return len(notices)


def _on_post_puppet(sender, session=None, **kwargs):
    """SIGNAL_OBJECT_POST_PUPPET receiver: deliver kept notices. Never raises."""
    try:
        deliver_pending(sender)
    except Exception:
        logger.exception(
            "evennia_lore.notices: delivering notices failed for #%s", getattr(sender, "pk", "?")
        )


def connect():
    """Connect notice delivery. Called from LoreConfig.ready()."""
    from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

    SIGNAL_OBJECT_POST_PUPPET.connect(_on_post_puppet, dispatch_uid="evennia_lore.notices")


def file_staff_review(title, description):
    """Pass a staff-review item to LORE_STAFF_REVIEW_HOOK, if one is set.

    Errors are logged, never raised: the lore action that prompted the review
    has already happened and must not be undone by a failed ticket.

    Returns:
        bool: True if the hook ran without error.
    """
    path = getattr(settings, "LORE_STAFF_REVIEW_HOOK", None)
    if not path:
        return False
    try:
        hook = import_string(path) if isinstance(path, str) else path
        hook(title, description)
    except Exception:
        logger.exception("evennia_lore.notices: LORE_STAFF_REVIEW_HOOK failed for %r", title)
        return False
    return True
