# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
AuthoringMixin — shared base for all evennia_jobs authoring (write) views.

Every write-capable view (create, comment) should mix this in. It provides:
  - LoginRequiredMixin enforcement.
  - A cached ``get_character()`` that raises PermissionDenied when the
    user has no active puppet.
  - ``get_permission_target()`` / ``check_permission()`` hooks so domain
    views can declare their own authoring rules in one place.
  - A ``form_valid()`` stub that intentionally raises NotImplementedError —
    forcing subclasses to call the model's factory classmethod rather than
    ``form.save()``.

Usage::

    class MyCreateView(AuthoringMixin, FormView):
        form_class = MyForm
        template_name = "evennia_jobs/my_form.html"

        def check_permission(self, character_id, target):
            pass  # anyone with a puppet can create

        def form_valid(self, form):
            character_id = self.get_character()
            MyModel.create_thing(author_id=character_id, **form.cleaned_data)
            return redirect(...)
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from evennia_jobs.permissions import is_staff_user, require_character


class AuthoringMixin(LoginRequiredMixin):
    """Mixin for all evennia_jobs authoring (write) views."""

    login_url = "/accounts/login/"

    def get_character(self) -> int:
        """Return the ObjectDB pk of the puppeted character.

        Cached on the view instance for the request lifetime.

        Raises:
            PermissionDenied: if the user is logged in but has no puppet.
        """
        if not hasattr(self, "_character_id"):
            self._character_id = require_character(self.request)
        return self._character_id

    def get_permission_target(self):
        """Return the object whose ownership will be checked, or None."""
        return None

    def check_permission(self, character_id: int, target) -> None:
        """Raise PermissionDenied if *character_id* may not act on *target*.

        Subclasses MUST override this.

        Raises:
            PermissionDenied: always in the base implementation.
        """
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
        """Intentionally unimplemented — subclasses must override."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.form_valid() must be overridden. "
            "Use the model's factory classmethod (e.g. Job.create_job()) "
            "rather than form.save()."
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_staff"] = is_staff_user(self.request)
        return context
