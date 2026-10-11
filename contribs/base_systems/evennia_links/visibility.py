# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Compatibility dispatch for room-only and viewer-aware privacy rules."""

from inspect import signature


def call_room_visibility(provider, room, viewer=None):
    """Invoke once, supporting (room), (room, viewer), or keyword-only viewer.

    Errors propagate to the caller's fail-closed privacy boundary.
    """
    sig = signature(provider)
    try:
        sig.bind(room, viewer=viewer)
    except TypeError:
        try:
            sig.bind(room, viewer)
        except TypeError:
            sig.bind(room)
            return bool(provider(room))
        return bool(provider(room, viewer))
    return bool(provider(room, viewer=viewer))


def request_viewer(request, *, staff=False):
    """Resolve a web preview's character once per request, not once per room.

    The request's user/selection must already be established by middleware.
    This cache lives only on that request, never on a room or shared plane.
    """
    if request is None or staff:
        return None
    if not hasattr(request, "_links_room_viewer"):
        from .characters import web_character

        request._links_room_viewer = web_character(getattr(request, "user", None))
    return request._links_room_viewer
