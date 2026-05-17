# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""MXP (MUD eXtension Protocol) helpers for clickable in-game URLs.

Two helpers:

- ``absolute_web_url(path)`` — promote a site-relative path to an absolute
  URL using the Django ``SITE_URL`` setting. Relative paths work fine for
  webclient MXP links (same origin) but break for external MXP telnet
  clients and outbound links in email or Discord digests.
- ``mxp_link(url, label)`` — wrap a URL and label string in Evennia's MXP
  link syntax (``|lu<url>|lt<label>|le``) so the client renders a clickable
  link with the given display text.

Compose them when sending a link out of the webclient context::

    from evennia_accessibility import absolute_web_url, mxp_link

    href = absolute_web_url(f"/scenes/{scene.pk}/")
    msg = f"View scene: {mxp_link(href, '[↗]')}"
"""

from django.conf import settings


def absolute_web_url(path):
    """Return an absolute URL for a site-relative path.

    Reads ``SITE_URL`` from Django settings (e.g. ``"https://yourgame.com"``).
    If ``SITE_URL`` is not configured, returns the relative path unchanged —
    relative paths work for webclient MXP links (same origin) but not for
    external MXP telnet clients or outbound links in email/Discord digests.

    Args:
        path: A site-relative URL path (e.g. ``/scenes/42/``).

    Returns:
        str: The absolute URL if ``SITE_URL`` is configured, otherwise the
        unchanged input path.

    Notes:
        Configure in your Django settings module::

            SITE_URL = "https://your-game-domain.example"
    """
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    if not base:
        return path
    return base + "/" + path.lstrip("/")


def mxp_link(url, label):
    """Return a MUSH MXP link string: ``|lu<url>|lt<label>|le``.

    Args:
        url: The href the client should open when the link is clicked.
        label: The display text shown in place of the URL.

    Returns:
        str: The MXP-encoded link string.

    Notes:
        For external/email/Discord contexts, wrap ``url`` in
        ``absolute_web_url()`` first so the link resolves outside the
        webclient origin.
    """
    return f"|lu{url}|lt{label}|le"
