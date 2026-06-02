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
