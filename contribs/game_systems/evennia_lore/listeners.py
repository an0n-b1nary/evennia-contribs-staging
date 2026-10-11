# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Signal listener for the passive lore trickle.

_on_rp_session_ended is registered in LoreConfig.ready() only when the
rptracker contrib is present. Without rptracker, the trickle is dormant
but the model and API still ship.
"""

import logging

logger = logging.getLogger("evennia")


def _on_rp_session_ended(sender, session, **kwargs):
    """Run passive lore trickle when an RPSession completes.

    Args:
        sender: RPSession model class.
        session: The completed RPSession instance.
    """
    try:
        character = session.character
        if character is None:
            return

        from evennia_lore.selection import select_passive_lore

        entry = select_passive_lore(character, session)
        if entry:
            character.msg(
                f"|wLore Acquired:|n You have passively learned about "
                f'|c"{entry.title}"|n (#{entry.entry_number}). '
                f"Use |w+lore/read {entry.entry_number}|n to read it."
            )
    except Exception:
        logger.exception(
            "evennia_lore.listeners: passive lore trickle failed for session #%s",
            getattr(session, "pk", "?"),
        )


def _on_plot_thread_concluded(sender, thread, concluded_by=None, **kwargs):
    """Remind whoever concluded a thread that its linked lore is still sealed.

    No automatic unsealing: staff settle each entry by hand with
    ``+lore/unseal``. The reminder goes to ``concluded_by`` (sent by
    evennia-plots 0.4.0 and later), falling back to the thread's creator. When
    that person isn't lore staff, the reminder is also filed through
    LORE_STAFF_REVIEW_HOOK, so a player-run thread can't strand a seal.

    Args:
        sender: PlotThread model class.
        thread: The concluded PlotThread.
        concluded_by: The character who concluded it, if the plots
            contrib sends one.
    """
    try:
        from evennia_lore.models import LoreEntry
        from evennia_lore.notices import file_staff_review, notify

        sealed = list(
            LoreEntry.objects.filter(plot_links__thread_id=thread.pk)
            .exclude(sealed_notes="")
            .order_by("entry_number")
            .distinct()
        )
        if not sealed:
            return
        numbers = ", ".join(f"#{entry.entry_number}" for entry in sealed)
        recipient = concluded_by or getattr(thread, "creator", None)
        if recipient is not None:
            notify(
                recipient,
                f"|y[Lore]|n Linked lore still sealed: {numbers}. "
                "Staff can unseal with |w+lore/unseal <id>=<accuracy>|n.",
            )

        from evennia_lore.commands import is_staff

        if recipient is None or not is_staff(recipient):
            name = getattr(thread, "name", "")
            number = getattr(thread, "plot_number", thread.pk)
            file_staff_review(
                f"Sealed lore on concluded plot #{number}",
                (
                    f"Plot thread #{number} '{name}' concluded with linked lore still "
                    f"sealed: {numbers}.\n\nUnseal each with +lore/unseal <id>=<accuracy> "
                    "when the story has settled it."
                ),
            )
    except Exception:
        logger.exception(
            "evennia_lore.listeners: sealed-lore reminder failed for thread #%s",
            getattr(thread, "pk", "?"),
        )
