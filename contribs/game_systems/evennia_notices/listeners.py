# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Never-breaking, session-scoped login/puppet summaries."""

import logging

from evennia_links.ignoring import ignore_policy_changing
from evennia_links.notices import session_context

logger = logging.getLogger("evennia")


def session_summary(sender, session=None, **kwargs):
    """Summarize only the account and puppet of this actual connection."""
    if session is None or session.get_account() is None:
        return
    from .services import summarize

    try:
        summarize(session_context(session))
    except Exception:
        logger.warning("Notice summary unavailable; login continues")


def register():
    """Connect idempotently without importing optional sources."""
    from evennia.server.signals import SIGNAL_ACCOUNT_POST_LOGIN, SIGNAL_OBJECT_POST_PUPPET

    from .services import snapshot_ignore

    SIGNAL_ACCOUNT_POST_LOGIN.connect(session_summary, dispatch_uid="notices.login")
    SIGNAL_OBJECT_POST_PUPPET.connect(session_summary, dispatch_uid="notices.puppet")
    ignore_policy_changing.connect(snapshot_ignore, dispatch_uid="notices.ignore")
