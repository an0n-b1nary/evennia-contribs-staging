# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""AuthoringMixin for evennia_lore write views (create, edit, lean)."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from evennia_lore.permissions import is_staff_user, require_character


class AuthoringMixin(LoginRequiredMixin):
    """Mixin for all evennia_lore authoring (write) views."""

    login_url = "/accounts/login/"

    def get_character(self) -> int:
        if not hasattr(self, "_character_id"):
            self._character_id = require_character(self.request)
        return self._character_id

    def get_permission_target(self):
        return None

    def check_permission(self, character_id: int, target) -> None:
        raise PermissionDenied("This view has not declared its permission rules.")

    def get(self, request, *args, **kwargs):
        character_id = self.get_character()
        target = self.get_permission_target()
        self.check_permission(character_id, target)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        character_id = self.get_character()
        target = self.get_permission_target()
        self.check_permission(character_id, target)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        raise NotImplementedError(
            f"{self.__class__.__name__}.form_valid() must be overridden. "
            "Use the model's factory classmethod rather than form.save()."
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_staff"] = is_staff_user(self.request)
        return context
