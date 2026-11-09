# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Optional, fail-open presentation filtering for comfort features.

Receivers of :data:`ignore_mode_requested` return ``None`` to abstain,
``"placeholder"`` to mask a presentation, or ``"hide"`` to omit it. Hiding
dominates masking. If any provider raises or returns an invalid value, the
whole evaluation returns ``None`` and logs once: these filters are not an
authorization or privacy boundary.

``ignore_policy_changing`` has a different contract. A receiver can persist
state that must be captured under the old policy immediately before an
effective policy mutation. It uses normal ``send`` so a bookkeeping failure
propagates and the caller can roll back the policy transaction. It is safe to
use when no provider is installed.
"""

import logging

from django.dispatch import Signal

ignore_mode_requested = Signal()  # viewer, sender, kind
ignore_policy_changing = Signal()  # viewer (account), kind (None or preference kind)
logger = logging.getLogger("evennia")


def ignore_mode(viewer, sender, kind):
    """Return ``None``, ``"placeholder"`` or ``"hide"`` for a presentation.

    Providers may abstain with ``None``. ``"hide"`` takes precedence over
    ``"placeholder"`` when providers compose. Any provider error or invalid
    result makes the complete evaluation fail open to ``None``.
    """
    mode = None
    invalid = False
    for _, result in ignore_mode_requested.send_robust(
        sender=ignore_mode, viewer=viewer, sender_object=sender, kind=kind
    ):
        if isinstance(result, Exception):
            logger.error(
                "Ignore presentation provider failed; showing content",
                exc_info=result,
            )
            return None
        if result is None:
            continue
        if not isinstance(result, str) or result not in {"placeholder", "hide"}:
            invalid = True
            continue
        if result == "hide":
            mode = "hide"
        elif mode is None:
            mode = "placeholder"

    if invalid:
        logger.error("Ignore presentation provider returned an invalid mode; showing content")
        return None
    return mode


def notify_ignore_policy_changing(viewer, kind=None):
    """Notify consumers immediately before an effective policy mutation.

    Call inside the transaction that locks ``viewer`` and applies the change.
    Receiver failures intentionally propagate, allowing that transaction to
    roll back instead of acknowledging a policy change without its required
    old-policy bookkeeping.
    """
    return ignore_policy_changing.send(
        sender=notify_ignore_policy_changing, viewer=viewer, kind=kind
    )


def notice_ignore_status(viewer, sender, policy_cache=None):
    """Return allow/suppress/defer for strict OOC notice policy.

    Unlike presentation filtering, provider errors must never expose activity.
    Both masking and hiding suppress a notice's text and count completely.
    """
    suppressed = False
    for _, result in ignore_mode_requested.send_robust(
        sender=notice_ignore_status,
        viewer=viewer,
        sender_object=sender,
        kind="notices",
        notice_cache=policy_cache,
    ):
        if isinstance(result, Exception) or result not in (None, "hide", "placeholder"):
            logger.warning("Notice ignore provider unavailable; deferring activity")
            return "defer"
        suppressed = suppressed or result is not None
    return "suppress" if suppressed else "allow"
