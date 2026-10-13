# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Coordinator-only frozen sources; pure provider callbacks never query DB."""

from importlib import import_module

from django.apps import apps


def contest_provider():
    if not apps.is_installed("evennia_rp_contest"):
        return None
    try:
        return import_module("evennia_rp_contest.bound")
    except ModuleNotFoundError as exc:
        if exc.name == "evennia_rp_contest.bound":
            return None  # Older optional Contest installs have no bound API.
        raise


def snapshot(subject, *, stats=None):
    provider = contest_provider()
    if provider is None:
        return None
    return provider.snapshot(subject, stats=stats)
