# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Monday-anchored period labels and a retrying queue for idempotent period batches.

A batch script ticks often (so shortened periods need no restart) but should
do real work only when a period completes. `advance()` keeps that bookkeeping
in a plain dict the script persists in an Attribute:

    state = advance(script.db.batch_state, period_key(seconds), run, paused=frozen)

- Each newly completed period is queued once and run as soon as it's due.
- `run(period, ids)` pays everyone when `ids` is None, otherwise only those
  character ids, and returns the ids that failed. Only failures are retried,
  with exponential backoff, and a period is dropped after `MAX_ATTEMPTS`
  (staff can still rerun it by hand; batches are idempotent).
- While `paused`, periods queue up and run oldest first once unpaused.
- Periods that complete while no script is ticking (the server is down) are
  never synthesized.
"""

import logging
import time
from datetime import UTC, datetime, timedelta

from django.utils import timezone

logger = logging.getLogger("evennia")
ANCHOR = datetime(1970, 1, 5, tzinfo=UTC)  # Monday 00:00 UTC
WEEK = 604800
RETRY_BASE = 300
RETRY_MAX = 6 * 3600
MAX_ATTEMPTS = 12
MAX_PENDING = 60


def period_key(seconds, reference=None):
    """Label the most recently completed period. Weekly periods use ISO weeks."""
    reference = (reference or timezone.now()).astimezone(UTC)
    index = int((reference - ANCHOR).total_seconds() // seconds)
    end = ANCHOR + timedelta(seconds=index * seconds)
    if seconds == WEEK:
        year, week, _ = (end - timedelta(seconds=1)).isocalendar()
        return f"{year}-W{week:02d}"
    return f"{seconds}s:{end.isoformat()}"


def _plain(state):
    from evennia.utils.dbserialize import deserialize

    state = deserialize(state) if state else {}
    return {"latest": state.get("latest"), "pending": list(state.get("pending") or [])}


def advance(state, current, run, *, now=None, paused=False, label="batch"):
    """Queue `current` if it's new, run every due period, and return the new state."""
    now = time.time() if now is None else now
    state = _plain(state)
    if current != state["latest"]:
        state["latest"] = current
        state["pending"].append({"period": current, "ids": None, "attempt": 0, "due": now})
        if len(state["pending"]) > MAX_PENDING:
            dropped = state["pending"][:-MAX_PENDING]
            state["pending"] = state["pending"][-MAX_PENDING:]
            logger.error("%s: dropped unpaid periods %s", label, [e["period"] for e in dropped])
    if paused:
        return state
    remaining = []
    for entry in state["pending"]:
        if entry["due"] > now:
            remaining.append(entry)
            continue
        try:
            failed = sorted(run(entry["period"], entry["ids"]) or [])
        except Exception:
            logger.exception("%s: period %s failed as a whole", label, entry["period"])
            failed = entry["ids"]  # None: retry everyone
        if failed == []:
            continue
        attempt = entry["attempt"] + 1
        if attempt >= MAX_ATTEMPTS:
            logger.error(
                "%s: giving up on period %s for %s after %s attempts",
                label,
                entry["period"],
                "everyone" if failed is None else failed,
                attempt,
            )
            continue
        delay = min(RETRY_BASE * 2 ** (attempt - 1), RETRY_MAX)
        remaining.append(
            {"period": entry["period"], "ids": failed, "attempt": attempt, "due": now + delay}
        )
    state["pending"] = remaining
    return state
