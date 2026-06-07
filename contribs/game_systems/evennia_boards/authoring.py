# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
BoardsAuthoringMixin — shared base for evennia_boards write views.

Provides LoginRequiredMixin enforcement, cached character resolution, and
get_permission_target() / check_permission() hooks. Requires [web] extra.
"""

from django.contrib.auth.mixins import LoginRequiredMixin

from evennia_boards.permissions import require_character


class BoardsAuthoringMixin(LoginRequiredMixin):
    """Mixin for all evennia_boards authoring (write) views."""

    login_url = "/accounts/login/"

    def get_character(self) -> int:
        """Return the ObjectDB pk of the puppeted character (cached per request).

        Raises:
            PermissionDenied: if logged in but no active puppet.
        """
        if not hasattr(self, "_character_id"):
            self._character_id = require_character(self.request)
        return self._character_id

    def get_permission_target(self):
        """Return the object whose permissions should be checked. Override in subclasses."""
        return None

    def check_permission(self, character_id, target):
        """Raise PermissionDenied if *character_id* cannot act on *target*. Override in subclasses."""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        # Character check on first dispatch so permission errors surface early.
        if request.user.is_authenticated:
            target = self.get_permission_target()
            if target is not None:
                character_id = self.get_character()
                self.check_permission(character_id, target)
        return response
