# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Settings and dotted-path helpers.

Everything that reads a setting goes through `setting()`, which falls back to
the default when Django settings aren't configured. That keeps the pipeline
usable from plain Python (a script, the odds tool, a unit test with no game)
as long as the caller passes the ruleset and roller explicitly.
"""

from __future__ import annotations

from importlib import import_module


def setting(name: str, default=None):
    """`settings.<name>`, or `default` if unset or Django isn't configured."""
    try:
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured
    except ImportError:  # pragma: no cover - Django is a hard dependency
        return default
    try:
        return getattr(settings, name, default)
    except ImproperlyConfigured:
        return default


def resolve_dotted(path: str):
    """Import and return the object at `path` (`"pkg.module.attr"`).

    Vendored rather than imported from `evennia_links` so this package keeps no
    dependency beyond Evennia; keep in step with `evennia_links.resolve_dotted`.

    Raises:
        ImportError: If `path` has no module part or the module won't import.
        AttributeError: If the module has no such attribute.
    """
    if not isinstance(path, str):
        raise ImportError(f"{path!r} is not a dotted path")
    module_path, _, attr = path.rpartition(".")
    if not module_path:
        raise ImportError(f"{path!r} is not a dotted path (expected 'pkg.module.attr')")
    return getattr(import_module(module_path), attr)
