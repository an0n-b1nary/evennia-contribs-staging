# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The website's chosen character, shared by every web contrib.

Evennia's website already lets an account pick a character: the
`character-puppet` link stores its id in the Django session under
`"puppet"`, and Evennia's own context shows it as `puppet`. Web contribs
resolve their acting character from `request.user` alone, through
`evennia_links.characters.web_character`, so they cannot read the session.
`WebCharacterMiddleware` passes the choice on for the length of one request,
and the context processor gives templates the character every contrib will
act as.

    MIDDLEWARE += ["evennia_links.web.WebCharacterMiddleware"]
    TEMPLATES[0]["OPTIONS"]["context_processors"] += [
        "evennia_links.web.web_character_context",
    ]

Without the middleware a choice made on the website is ignored and the
resolver's own order applies.
"""

from .characters import _web_choice, web_character, web_roster

SESSION_KEY = "puppet"  # Evennia's CharacterPuppetView stores the choice here


class WebCharacterMiddleware:
    """Expose the session's chosen character to `web_character` for one request.

    Must come after Django's session and authentication middleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        choice = None
        user = getattr(request, "user", None)
        session = getattr(request, "session", None)
        if session is not None and getattr(user, "is_authenticated", False):
            try:
                choice = (user.pk, int(session.get(SESSION_KEY)))
            except (TypeError, ValueError):
                choice = None
        token = _web_choice.set(choice)
        try:
            return self.get_response(request)
        finally:
            _web_choice.reset(token)


def web_character_context(request):
    """`web_character` (the character web pages act as) and `web_roster` for templates."""
    user = getattr(request, "user", None)
    return {"web_character": web_character(user), "web_roster": web_roster(user)}
