# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
evennia_jobs — staff ticket system for Evennia games.

Public API (model classes are loaded lazily to avoid AppRegistryNotReady
when this package is imported during Django's app-loading phase):

    Job             — ticket model
    JobComment      — comment model
    JobType         — enum: REQUEST / BUG / ISSUE / DISCUSS
    JobStatus       — enum: OPEN / IN_REVIEW / ANSWERED / CLOSED
    JobPriority     — enum: NORMAL / HIGH / URGENT

Commands (import explicitly when needed):

    from evennia_jobs.commands import CmdRequest, CmdBug, CmdIssue, CmdDiscuss, CmdJobs

Web/API surface (requires [web] extra):

    from evennia_jobs.views import JobListView, JobDetailView, ...
    from evennia_jobs.api.views import JobViewSet
    from evennia_jobs import urls, api.urls
"""

__version__ = "0.1.0"

_LAZY = {
    "Job": "models",
    "JobComment": "models",
    "JobType": "models",
    "JobStatus": "models",
    "JobPriority": "models",
}

__all__ = [
    "Job",
    "JobComment",
    "JobPriority",
    "JobStatus",
    "JobType",
]


def __getattr__(name):
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{submodule}", __name__), name)


def __dir__():
    return sorted([*globals(), *_LAZY])
