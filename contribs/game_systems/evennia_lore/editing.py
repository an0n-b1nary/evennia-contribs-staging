# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Reusable editing framework for version-tracked text editing.

Provides EditingMixin and module-level EvEditor callbacks. Designed to be
mixed into MuxCommand subclasses that need versioned editing of model text
fields (e.g. LoreEntry.body).

Candidate for future hoisting into evennia-links (shared with the plots
contrib). Shipped here as a local copy to keep evennia-lore self-contained.

Usage::

    from evennia_lore.editing import EditingMixin

    class CmdLore(EditingMixin, MuxCommand):
        def func(self):
            self.start_edit(entry, field_name="body", version_model_class=LoreVersion)
"""

import difflib

from evennia.utils.eveditor import EvEditor

VERSIONS_PER_PAGE = 10


def _load_func(caller):
    """EvEditor loadfunc: return the current field content."""
    ctx = caller.ndb._editing_context
    if not ctx:
        return ""
    try:
        instance = ctx["model_class"].objects.get(pk=ctx["instance_pk"])
    except ctx["model_class"].DoesNotExist:
        caller.msg("|rError: the object you were editing no longer exists.|n")
        return ""
    return getattr(instance, ctx["field_name"], "")


def _save_func(caller, buffer):
    """EvEditor savefunc: save buffer to the model field with optional versioning."""
    ctx = caller.ndb._editing_context
    if not ctx:
        caller.msg("|rError: no editing context found.|n")
        return False

    try:
        instance = ctx["model_class"].objects.get(pk=ctx["instance_pk"])
    except ctx["model_class"].DoesNotExist:
        caller.msg("|rError: the object you were editing no longer exists.|n")
        return False

    old_content = getattr(instance, ctx["field_name"], "")
    new_content = buffer.strip()

    if new_content == old_content.strip():
        caller.msg("No changes to save.")
        return True

    version_cls = ctx.get("version_model_class")
    if version_cls:
        version_cls.create_version(parent=instance, content=old_content, editor=caller)

    setattr(instance, ctx["field_name"], new_content)
    instance.save(update_fields=[ctx["field_name"]])
    caller.msg("Content saved.")
    return True


def _quit_func(caller):
    """EvEditor quitfunc: clean up the editing context."""
    caller.ndb._editing_context = None
    caller.msg("Editor closed.")


def _new_save_func(caller, buffer):
    """EvEditor savefunc for new content creation (calls stored callback)."""
    ctx = caller.ndb._editing_context
    if not ctx:
        caller.msg("|rError: no editing context found.|n")
        return False

    callback = ctx.get("create_callback")
    if not callback:
        caller.msg("|rError: no create callback found.|n")
        return False

    content = buffer.strip()
    if not content:
        caller.msg("Nothing to save — buffer is empty.")
        return False

    callback(caller, content)
    return True


def _new_quit_func(caller):
    """EvEditor quitfunc for new content creation."""
    caller.ndb._editing_context = None
    caller.msg("Editor closed.")


class EditingMixin:
    """
    Mixin for MuxCommand subclasses that need version-tracked text editing.

    Provides start_edit, start_new_edit, view_versions, do_rollback, view_diff.
    """

    def start_edit(self, instance, field_name="content", version_model_class=None):
        """Begin an EvEditor session on an existing object's text field."""
        caller = self.caller
        if getattr(caller.ndb, "_editing_context", None):
            caller.msg(
                "You already have an editing session open. "
                "Finish or quit it first (|w:q|n or |w:wq|n)."
            )
            return

        caller.ndb._editing_context = {
            "model_class": type(instance),
            "instance_pk": instance.pk,
            "field_name": field_name,
            "version_model_class": version_model_class,
        }
        EvEditor(
            caller,
            loadfunc=_load_func,
            savefunc=_save_func,
            quitfunc=_quit_func,
            key="lore_editor",
            persistent=False,
        )

    def start_new_edit(self, callback):
        """Begin an EvEditor session for creating new content."""
        caller = self.caller
        if getattr(caller.ndb, "_editing_context", None):
            caller.msg(
                "You already have an editing session open. "
                "Finish or quit it first (|w:q|n or |w:wq|n)."
            )
            return

        caller.ndb._editing_context = {"create_callback": callback}
        EvEditor(
            caller,
            loadfunc=lambda caller: "",
            savefunc=_new_save_func,
            quitfunc=_new_quit_func,
            key="lore_editor",
            persistent=False,
        )

    def view_versions(self, instance, version_model_class, page=1):
        """Display paginated version history for an object."""
        caller = self.caller
        qs = version_model_class.objects.filter(parent=instance).order_by("-version_number")

        if not caller.locks.check_lockstring(caller, "perm(Builder)"):
            qs = qs.filter(editor=caller)

        total = qs.count()
        if total == 0:
            caller.msg("No version history found.")
            return

        total_pages = (total + VERSIONS_PER_PAGE - 1) // VERSIONS_PER_PAGE
        page = max(1, min(page, total_pages))
        start = (page - 1) * VERSIONS_PER_PAGE
        versions = qs[start : start + VERSIONS_PER_PAGE]

        lines = [f"|wVersion History|n (page {page}/{total_pages})", "-" * 50]
        for v in versions:
            rollback_tag = " |y[rollback]|n" if v.is_rollback else ""
            lines.append(
                f"  v{v.version_number} | {v.editor_name} | "
                f"{v.created_at.strftime('%Y-%m-%d %H:%M')}{rollback_tag}"
            )
        lines.append("-" * 50)
        if total_pages > 1:
            lines.append(f"Use page 1-{total_pages} to navigate.")
        caller.msg("\n".join(lines))

    def do_rollback(self, instance, version_model_class, version_number, field_name="content"):
        """Rollback an object's text field to a previous version."""
        caller = self.caller
        old_content = getattr(instance, field_name, "")
        version_model_class.create_version(parent=instance, content=old_content, editor=caller)

        try:
            rollback_version = version_model_class.rollback_to(
                parent=instance, version_number=version_number, editor=caller
            )
        except version_model_class.DoesNotExist:
            caller.msg(f"|rVersion {version_number} not found.|n")
            return

        setattr(instance, field_name, rollback_version.content)
        instance.save(update_fields=[field_name])
        caller.msg(
            f"Rolled back to version {version_number} "
            f"(saved as v{rollback_version.version_number})."
        )

    def view_diff(self, instance, version_model_class, version_number, field_name="content"):
        """Show diff between a LoreVersion snapshot and current content."""
        caller = self.caller

        try:
            version = version_model_class.objects.get(
                parent=instance, version_number=version_number
            )
        except version_model_class.DoesNotExist:
            caller.msg(f"|rVersion {version_number} not found.|n")
            return

        current = getattr(instance, field_name, "")
        old = version.content

        lines = [
            f"|wVersion {version_number}|n by {version.editor_name} "
            f"({version.created_at.strftime('%Y-%m-%d %H:%M')})"
        ]
        if version.is_rollback:
            lines.append(f"|y[Rollback from v{version.rolled_back_from}]|n")
        lines.append("-" * 50)

        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"v{version_number}",
            tofile="current",
        )
        diff_text = "".join(diff)
        if diff_text:
            lines.append("|wDiff vs. current:|n")
            lines.append(diff_text)
        else:
            lines.append("(identical to current content)")

        lines.append("-" * 50)
        lines.append(f"|wFull content at v{version_number}:|n")
        lines.append(old if old else "(empty)")
        caller.msg("\n".join(lines))
