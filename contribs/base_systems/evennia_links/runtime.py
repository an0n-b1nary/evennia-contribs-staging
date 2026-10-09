# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Registered, validated runtime settings backed by Evennia's ServerConfig.

Providers register in AppConfig.ready(). Reads deliberately have no process
cache: staff edits become visible to other server processes immediately.
"""

import builtins
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.dispatch import Signal

logger = logging.getLogger("evennia")
runtime_setting_changed = Signal()  # name, value, by (also on reset)
cap_contributions = Signal()  # character; {provider: {money: int, resources: int}}


@dataclass(frozen=True)
class RuntimeSetting:
    default: object
    validator: object
    description: str


_registry = {}


def register(name, default, *, validator, description=""):
    """Register a public setting name. Repeated identical registrations are safe."""
    if not isinstance(name, str) or not name.isidentifier() or not name.isupper():
        raise ValueError("Runtime setting names must be uppercase identifiers.")
    entry = RuntimeSetting(default, validator, description)
    if name in _registry and _registry[name] != entry:
        raise ValueError(f"Runtime setting {name} is already registered differently.")
    if not validator(default):
        raise ValueError(f"Invalid default for {name}.")
    _registry[name] = entry


def registered():
    return dict(_registry)


def _entry(name):
    try:
        return _registry[name]
    except KeyError:
        raise ValueError(f"{name} is not registered as runtime-tunable.") from None


def get(name):
    """Return the DB override, host setting, or registered default (in that order)."""
    from evennia.server.models import ServerConfig
    from evennia.utils.dbserialize import from_pickle

    entry = _entry(name)
    # Avoid Evennia's model-instance identity cache: another process may have
    # changed the row while this process still holds its old ServerConfig.
    raw = (
        ServerConfig.objects.filter(db_key=f"runtime:{name}")
        .values_list("db_value", flat=True)
        .first()
    )
    stored = from_pickle(raw) if raw is not None else None
    value = stored["value"] if stored is not None else getattr(settings, name, entry.default)
    if not entry.validator(value):
        raise ValueError(f"Invalid value for runtime setting {name}.")
    return value


def set(name, value, *, by=None):
    """Persist a validated override; log the actor and notify after commit."""
    from evennia.server.models import ServerConfig

    if not _entry(name).validator(value):
        raise ValueError(f"Invalid value for {name}.")
    actor = getattr(by, "pk", by)
    with transaction.atomic():
        ServerConfig.objects.conf(f"runtime:{name}", {"value": value, "by": actor})
        transaction.on_commit(lambda: _changed(name, value, actor))


def reset(name, *, by=None):
    """Remove an override, restoring the host setting or package default."""
    from evennia.server.models import ServerConfig

    entry = _entry(name)
    value = getattr(settings, name, entry.default)
    if not entry.validator(value):
        raise ValueError(f"Invalid host value for {name}.")
    actor = getattr(by, "pk", by)
    with transaction.atomic():
        ServerConfig.objects.conf(f"runtime:{name}", delete=True)
        transaction.on_commit(lambda: _changed(name, value, actor))


def _changed(name, value, by):
    logger.info("Runtime setting %s changed to %r by #%s", name, value, by)
    runtime_setting_changed.send_robust(sender=RuntimeSetting, name=name, value=value, by=by)


def cap_raise(character, kind):
    """Sum nonnegative integer raises under disjoint provider keys."""
    from .collect import collect_dicts

    contributions = collect_dicts(cap_contributions, sender=RuntimeSetting, character=character)
    total = 0
    for provider, values in contributions.items():
        amount = values.get(kind, 0) if isinstance(values, dict) else None
        if type(amount) is not builtins.int or amount < 0:
            logger.error("Invalid %s cap contribution from %s: %r", kind, provider, values)
            continue
        total += amount
    return total
