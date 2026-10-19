# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Notices to players about their RSVPs.

The calendar tells a player when they're drawn in a lottery, seated by a
cluster draw, given a place from the waitlist, invited or offered a place by a
host, and reminded before an event they're confirmed for. ``notify()`` tells a
connected character at once; otherwise the notice waits as a ``CalendarNotice``
row until the character is next puppeted. A waiting notice is dropped unread if
its RSVP has changed status since, or the event was cancelled or has started.

The receivers below listen to the calendar's own signals and are connected in
``CalendarConfig.ready()``, along with delivery on Evennia's
``SIGNAL_OBJECT_POST_PUPPET``, so a game needs no typeclass wiring. None of
them raises: a failed notice is logged and never breaks a draw or a command.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger("evennia")

TIME_FORMAT = "%Y-%m-%d %H:%M"


def is_online(character):
    """Return True if *character* is puppeted by at least one session."""
    try:
        return bool(character.sessions.count())
    except Exception:
        return False


def notify(rsvp, kind, message):
    """Tell *rsvp*'s character *message* now if they're connected, otherwise at next puppet.

    A reminder is sent at most once per RSVP; a repeat is ignored.

    Args:
        rsvp (RSVP): The RSVP the notice is about.
        kind (str): A ``CalendarNotice.Kind`` value.
        message (str): The notice, already formatted.

    Returns:
        bool: True if delivered now, False if kept for later or not sent.
    """
    from evennia_calendar.models import CalendarNotice

    character = rsvp.character
    if character is None:
        return False
    try:
        with transaction.atomic():
            notice = CalendarNotice.objects.create(
                rsvp=rsvp, character=character, kind=kind, status=rsvp.status, message=message
            )
    except IntegrityError:
        return False  # This RSVP's reminder was already sent.
    if not is_online(character):
        return False
    character.msg(message)
    CalendarNotice.objects.filter(pk=notice.pk).update(delivered_at=timezone.now())
    return True


def _still_current(notice):
    rsvp = notice.rsvp
    event = rsvp.event
    return rsvp.status == notice.status and not event.is_cancelled and not event.is_past


def deliver_pending(character):
    """Send *character* each waiting notice that still applies, oldest first.

    Notices that no longer apply are marked delivered without being shown.

    Returns:
        int: How many notices were shown.
    """
    from evennia_calendar.models import CalendarNotice

    waiting = list(
        CalendarNotice.objects.filter(character=character, delivered_at__isnull=True)
        .select_related("rsvp__event")
        .order_by("created_at", "pk")
    )
    if not waiting:
        return 0
    shown = [notice.message for notice in waiting if _still_current(notice)]
    if shown:
        character.msg("\n".join(shown))
    CalendarNotice.objects.filter(pk__in=[notice.pk for notice in waiting]).update(
        delivered_at=timezone.now()
    )
    return len(shown)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _when(event):
    return f"{event.scheduled_time.strftime(TIME_FORMAT)} UTC"


def _confirm_by(event):
    return (
        f"Confirm with |w+rsvp/confirm {event.pk}|n by "
        f"{event.confirmation_deadline.strftime(TIME_FORMAT)} UTC, "
        "or the place goes to someone else."
    )


def drawn_message(event):
    return f"|yYou were drawn for |w'{event.title}'|n ({_when(event)}).|n {_confirm_by(event)}"


def invited_message(event, host=None):
    who = f"{host} has invited you" if host else "You've been invited"
    return f"|y{who} to |w'{event.title}'|n ({_when(event)}).|n {_confirm_by(event)}"


def offered_message(event):
    return f"|yA place has opened for |w'{event.title}'|n ({_when(event)}).|n {_confirm_by(event)}"


def seated_message(event):
    return (
        f"|yA place opened for |w'{event.title}'|n ({_when(event)}), "
        "and it's yours: you're confirmed.|n"
    )


def reminder_message(event):
    return f"|yReminder:|n |w'{event.title}'|n starts at {_when(event)}."


# ---------------------------------------------------------------------------
# Signal receivers
# ---------------------------------------------------------------------------


def _safely(what, rsvp, func):
    try:
        func()
    except Exception:
        logger.exception(
            "evennia_calendar.notices: %s notice failed for RSVP #%s",
            what,
            getattr(rsvp, "pk", "?"),
        )


def on_lottery_selected(sender, event=None, rsvp=None, **kwargs):
    """lottery_selected receiver: tell the player they were drawn."""
    _safely("drawn", rsvp, lambda: notify(rsvp, "drawn", drawn_message(event)))


def on_cluster_seat_assigned(sender, rsvp=None, **kwargs):
    """cluster_seat_assigned receiver: a cluster draw seats like a lottery draw."""
    _safely("drawn", rsvp, lambda: notify(rsvp, "drawn", drawn_message(rsvp.event)))


def on_waitlist_promoted(sender, event=None, rsvp=None, **kwargs):
    """waitlist_promoted receiver: a place given outright, or offered to confirm."""
    from evennia_calendar.models import RSVP

    if rsvp.status == RSVP.Status.CONFIRMED:
        _safely("seated", rsvp, lambda: notify(rsvp, "seated", seated_message(event)))
    elif rsvp.status == RSVP.Status.INVITED:
        _safely("invited", rsvp, lambda: notify(rsvp, "invited", offered_message(event)))


def on_event_starting_soon(sender, event=None, **kwargs):
    """event_starting_soon receiver: remind everyone confirmed, once each."""
    from evennia_calendar.models import RSVP

    if event is None or event.is_cancelled:
        return
    message = reminder_message(event)
    for rsvp in event.rsvps.filter(status=RSVP.Status.CONFIRMED).select_related("character"):
        _safely("reminder", rsvp, lambda rsvp=rsvp: notify(rsvp, "reminder", message))


def on_post_puppet(sender, session=None, **kwargs):
    """SIGNAL_OBJECT_POST_PUPPET receiver: deliver waiting notices. Never raises."""
    try:
        deliver_pending(sender)
    except Exception:
        logger.exception(
            "evennia_calendar.notices: delivering notices failed for #%s",
            getattr(sender, "pk", "?"),
        )


def connect():
    """Connect the receivers. Called from ``CalendarConfig.ready()``; safe to repeat."""
    from evennia.server.signals import SIGNAL_OBJECT_POST_PUPPET

    from evennia_calendar import signals

    signals.lottery_selected.connect(
        on_lottery_selected, dispatch_uid="evennia_calendar.notice_drawn"
    )
    signals.cluster_seat_assigned.connect(
        on_cluster_seat_assigned, dispatch_uid="evennia_calendar.notice_cluster"
    )
    signals.waitlist_promoted.connect(
        on_waitlist_promoted, dispatch_uid="evennia_calendar.notice_waitlist"
    )
    signals.event_starting_soon.connect(
        on_event_starting_soon, dispatch_uid="evennia_calendar.notice_reminder"
    )
    SIGNAL_OBJECT_POST_PUPPET.connect(on_post_puppet, dispatch_uid="evennia_calendar.notices")
