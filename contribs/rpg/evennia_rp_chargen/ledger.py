# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The XP ledger seam: where ability costs go once the allowance runs out.

chargen never touches an XP table itself. `settings.RP_CHARGEN_XP_LEDGER`
names a zero-argument factory returning something with this shape:

    class XPLedger(Protocol):
        def balance(self, character) -> Decimal: ...
        def spend(self, character, amount, *, ref_key, reason="") -> None: ...
        def refund(self, character, *, ref_key) -> Decimal: ...

`spend` raises `InsufficientXP` when the balance is short, and must be
idempotent on `ref_key`. Without a ledger, `NullLedger` is used: a balance of
zero, so abilities are bought from the starting allowance only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from evennia_rp_chargen import conf


class InsufficientXP(Exception):
    """The ledger can't cover a spend."""


class LedgerUnavailable(Exception):
    """No XP ledger is configured, so only the allowance can pay."""


@runtime_checkable
class XPLedger(Protocol):
    def balance(self, character) -> Decimal: ...

    def spend(self, character, amount: Decimal, *, ref_key: str, reason: str = "") -> None: ...

    def refund(self, character, *, ref_key: str) -> Decimal: ...


class NullLedger:
    """No XP: everything is paid from the starting allowance."""

    available = False

    def balance(self, character) -> Decimal:
        return Decimal(0)

    def spend(self, character, amount, *, ref_key, reason=""):
        raise LedgerUnavailable("XP spending isn't available in this game")

    def refund(self, character, *, ref_key):
        raise LedgerUnavailable("XP spending isn't available in this game")


def get_ledger() -> XPLedger:
    """`RP_CHARGEN_XP_LEDGER()`, or a `NullLedger`.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If the path won't import.
    """
    path = conf.get("RP_CHARGEN_XP_LEDGER")
    if not path:
        return NullLedger()
    from django.core.exceptions import ImproperlyConfigured

    from evennia_links import resolve_dotted

    try:
        return resolve_dotted(path)()
    except (ImportError, AttributeError) as exc:
        raise ImproperlyConfigured(f"RP_CHARGEN_XP_LEDGER: can't import {path!r}: {exc}") from exc


__all__ = ["InsufficientXP", "LedgerUnavailable", "NullLedger", "XPLedger", "get_ledger"]
