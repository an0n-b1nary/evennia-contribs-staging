# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Shared signal-listener registration helper.

Provides a small import-order-safe utility for wiring Django signals to
receivers during AppConfig.ready().

Usage::

    # In your AppConfig.ready():
    from evennia_links import connect_on_ready
    from myapp.signals import something_happened
    from myapp.listeners import on_something_happened

    connect_on_ready(something_happened, on_something_happened)

Django deduplicates repeated signal.connect() calls for the same receiver,
so calling this multiple times (e.g. if ready() fires more than once in
tests) is safe.

Why use this instead of calling signal.connect() directly?
The indirection enforces the pattern of *never* importing domain-app signals
at module level — always inside a ready() call. This prevents circular
imports when two apps each listen to each other's signals.
"""


def connect_on_ready(signal, receiver):
    """
    Import-order-safe lazy connect. Call from AppConfig.ready().

    Django dedupes repeated connections, so multiple ready() calls are safe.

    Args:
        signal: A Django Signal instance.
        receiver: The callable to connect as a listener.
    """
    signal.connect(receiver)
