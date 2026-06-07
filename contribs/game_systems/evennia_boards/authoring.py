# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
BoardsAuthoringMixin — shared base for evennia_boards write views.

Provides LoginRequiredMixin enforcement, cached character resolution, and
get_permission_target() / check_permission() hooks. Requires [web] extra.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from evennia_boards.permissions import require_character


class BoardsAuthoringMixin(LoginRequiredMixin):
    """Mixin for all evennia_boards authoring (write) views.

    Combine with Django's ``FormView``, ``CreateView``, or ``UpdateView``.
    The permission gate runs in ``get()``/``post()`` *before* the parent
    view executes, so an unauthorised request never reaches ``form_valid``
    (and therefore never writes to the database).
    """

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
        """Return the object whose permissions should be checked.

        For create views this is typically the parent container (e.g. the
        board); for edit views it is the object being edited. Override in
        subclasses.
        """
        return None

    def check_permission(self, character_id, target):
        """Raise PermissionDenied if *character_id* may not act on *target*.

        The default implementation denies everything — subclasses MUST
        override this to declare their own access rules.

        Raises:
            PermissionDenied: always, in the base implementation.
        """
        raise PermissionDenied("This view has not declared its permission rules.")

    def get(self, request, *args, **kwargs):
        character_id = self.get_character()
        self.check_permission(character_id, self.get_permission_target())
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        character_id = self.get_character()
        self.check_permission(character_id, self.get_permission_target())
        return super().post(request, *args, **kwargs)
