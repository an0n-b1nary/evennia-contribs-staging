# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Lore compendium commands for evennia_lore.

Add to your CharacterCmdSet::

    from evennia_lore.commands import (
        CmdLore, CmdInvestigate, CmdShare, CmdHint, CmdForget
    )

Settings:
  LORE_STAFF_LOCK — lock string for staff operations (default "cmd:perm(Builder)").
  LORE_SCENES_APP_LABEL  — app label for the scenes model (default "scenes").
  LORE_PLOTS_APP_LABEL   — app label for the plots/PlotThread model (default "plots").
  LORE_REGIONS_APP_LABEL — app label for the regions model (default "regions").
"""

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand

from evennia_links import EditingMixin
from evennia_lore.models import (
    LoreAcquisition,
    LoreEntry,
    LoreRegionLink,
    LoreSceneLink,
    LoreTag,
    LoreVersion,
    PlotLoreLink,
)

try:
    from evennia_accessibility import uses_screenreader
except ImportError:

    def uses_screenreader(_):
        """Fallback when evennia-accessibility is not installed."""
        return False


def is_staff(character):
    """Return True if *character* has lore staff permission level (LORE_STAFF_LOCK)."""
    lock_expr = getattr(settings, "LORE_STAFF_LOCK", "cmd:perm(Builder)")
    expr = lock_expr[4:] if lock_expr.startswith("cmd:") else lock_expr
    try:
        return bool(character.locks.check_lockstring(character, expr))
    except Exception:
        return False


def _web_link(entry):
    """Return an MXP web link for a lore entry, or empty string if not available."""
    try:
        path = f"/lore/{entry.pk}/"
        return f" |lu{path}|lt[↗]|le"
    except Exception:
        return ""


_PAGE_SIZE = 10


def _resolve_entry(arg, caller, require_published=False):
    """Resolve a LoreEntry by entry_number (#N) or title substring.

    Returns:
        (LoreEntry, None) on success.
        (None, error_str) on failure.
    """
    arg = arg.strip()
    staff = is_staff(caller)

    qs = (
        LoreEntry.objects.all()
        if staff
        else LoreEntry.objects.filter(status=LoreEntry.Status.PUBLISHED)
    )
    if require_published:
        qs = LoreEntry.objects.filter(status=LoreEntry.Status.PUBLISHED)

    if arg.startswith("#"):
        num_str = arg[1:]
        if not num_str.isdigit():
            return None, f"'{arg}' is not a valid entry ID. Use #N (e.g. #5)."
        try:
            return qs.get(entry_number=int(num_str)), None
        except LoreEntry.DoesNotExist:
            return None, f"No lore entry #{num_str} found."

    try:
        return qs.get(title__iexact=arg), None
    except LoreEntry.DoesNotExist:
        pass
    except LoreEntry.MultipleObjectsReturned:
        return None, f"Multiple entries match '{arg}'. Use #N to be specific."

    matches = list(qs.filter(title__icontains=arg))
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        titles = ", ".join(f"#{e.entry_number} {e.title}" for e in matches[:5])
        return None, f"Multiple entries match '{arg}': {titles}. Use #N to be specific."

    return None, f"No lore entry matching '{arg}' found."


def _can_edit_entry(entry, caller):
    """Return True if caller is the entry author or staff."""
    if is_staff(caller):
        return True
    return entry.author_id and caller.id == entry.author_id


def _format_entry_row(entry):
    """One-line compendium list row for a LoreEntry."""
    lock_badge = " |r[RESTRICTED]|n" if entry.privacy == LoreEntry.Privacy.RESTRICTED else ""
    return f"  |w#{entry.entry_number}|n {entry.title}{lock_badge}{_web_link(entry)}"


def _get_model(label_setting_key, model_name, default_label):
    """Lazily load a model from a settings-configured app label."""
    from django.apps import apps

    label = getattr(settings, label_setting_key, default_label)
    return apps.get_model(label, model_name)


# ---------------------------------------------------------------------------
# CmdLore
# ---------------------------------------------------------------------------


class CmdLore(EditingMixin, MuxCommand):
    """
    View and manage the lore compendium.

    Usage:
        +lore                              Browse PUBLISHED entries (paginated)
        +lore/read <id>                    Read an entry's full body
        +lore/search <term>                Search by title or body text
        +lore/submit <title>               Open editor to write a new entry
        +lore/submit/scene <scene#>=<title> Submit + auto-link to a scene
        +lore/edit <id>                    Edit your entry's body (EvEditor)
        +lore/tag <id>=<tag>               Add a tag (creates if new)
        +lore/tag/major <id>=<tag>         Add a major tag (staff only)
        +lore/untag <id>=<tag>             Remove a tag
        +lore/region <id>=<region>         Associate entry with a region
        +lore/unregion <id>=<region>       Remove a region association
        +lore/object <id>=<#objref>        Tag entry to an in-game object
        +lore/unobject <id>=<#objref>      Remove object tag
        +lore/link/scene <id>=<scene#>     Link entry to a scene
        +lore/link/plot <id>=<plot#>       Link entry to a plot thread
        +lore/approve <id>                 Approve a submitted entry (staff only)
        +lore/reject <id>=<reason>         Reject a submitted entry (staff only)
        +lore/flag <id>=<reason>           Flag an entry for staff review
        +lore/unflag <id>                  Clear a flag (staff only)
        +lore/history <id>                 View edit history for an entry
        +lore/diff <id>=<version#>         Show diff between a version and current
        +lore/acquired                     List entries you have acquired
        +lore/queue                        List entries awaiting approval (staff only)
    """

    key = "+lore"
    aliases = []  # noqa: RUF012
    help_category = "Lore"
    locks = "cmd:all()"

    def func(self):
        sw = self.switches
        caller = self.caller
        args = self.args.strip()
        lhs = self.lhs.strip() if self.lhs else ""
        rhs = self.rhs.strip() if self.rhs else ""

        if not sw:
            page = int(args) if args.isdigit() else 1
            return self._do_browse(page=page)

        if "read" in sw:
            if not args and not lhs:
                caller.msg("Usage: |w+lore/read <id>|n")
                return
            return self._do_read(lhs or args)

        if "search" in sw:
            if not args and not lhs:
                caller.msg("Usage: |w+lore/search <term>|n")
                return
            return self._do_search(lhs or args)

        if "submit" in sw:
            if "scene" in sw:
                if not lhs or not rhs:
                    caller.msg("Usage: |w+lore/submit/scene <scene#>=<title>|n")
                    return
                return self._do_submit(rhs, scene_arg=lhs)
            title = lhs or args
            if not title:
                caller.msg("Usage: |w+lore/submit <title>|n")
                return
            return self._do_submit(title)

        if "edit" in sw:
            if not lhs and not args:
                caller.msg("Usage: |w+lore/edit <id>|n")
                return
            return self._do_edit(lhs or args)

        if "tag" in sw and "untag" not in sw:
            make_major = "major" in sw
            if not lhs or not rhs:
                caller.msg("Usage: |w+lore/tag <id>=<tag>|n")
                return
            return self._do_tag(lhs, rhs, make_major=make_major)

        if "untag" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+lore/untag <id>=<tag>|n")
                return
            return self._do_untag(lhs, rhs)

        if "region" in sw and "unregion" not in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+lore/region <id>=<region name>|n")
                return
            return self._do_region(lhs, rhs)

        if "unregion" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+lore/unregion <id>=<region name>|n")
                return
            return self._do_unregion(lhs, rhs)

        if "object" in sw and "unobject" not in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+lore/object <id>=<#objref>|n")
                return
            return self._do_object(lhs, rhs)

        if "unobject" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+lore/unobject <id>=<#objref>|n")
                return
            return self._do_unobject(lhs, rhs)

        if "link" in sw:
            if "scene" in sw:
                if not lhs or not rhs:
                    caller.msg("Usage: |w+lore/link/scene <id>=<scene#>|n")
                    return
                return self._do_link_scene(lhs, rhs)
            if "plot" in sw:
                if not lhs or not rhs:
                    caller.msg("Usage: |w+lore/link/plot <id>=<plot#>|n")
                    return
                return self._do_link_plot(lhs, rhs)
            caller.msg("Specify: |w+lore/link/scene|n or |w+lore/link/plot|n")
            return

        if "approve" in sw:
            if not is_staff(caller):
                caller.msg("Only staff can approve entries.")
                return
            if not lhs and not args:
                caller.msg("Usage: |w+lore/approve <id>|n")
                return
            return self._do_approve(lhs or args)

        if "reject" in sw:
            if not is_staff(caller):
                caller.msg("Only staff can reject entries.")
                return
            if not lhs:
                caller.msg("Usage: |w+lore/reject <id>=<reason>|n")
                return
            return self._do_reject(lhs, rhs)

        if "flag" in sw and "unflag" not in sw:
            if not lhs:
                caller.msg("Usage: |w+lore/flag <id>=<reason>|n")
                return
            return self._do_flag(lhs, rhs)

        if "unflag" in sw:
            if not is_staff(caller):
                caller.msg("Only staff can clear flags.")
                return
            if not lhs and not args:
                caller.msg("Usage: |w+lore/unflag <id>|n")
                return
            return self._do_unflag(lhs or args)

        if "history" in sw:
            if not lhs and not args:
                caller.msg("Usage: |w+lore/history <id>|n")
                return
            return self._do_history(lhs or args)

        if "diff" in sw:
            if not lhs or not rhs:
                caller.msg("Usage: |w+lore/diff <id>=<version#>|n")
                return
            return self._do_diff(lhs, rhs)

        if "acquired" in sw:
            return self._do_acquired()

        if "queue" in sw:
            if not is_staff(caller):
                caller.msg("Only staff can view the approval queue.")
                return
            return self._do_queue()

        caller.msg("Unknown switch. See |w+help +lore|n for options.")

    def _do_browse(self, page=1):
        caller = self.caller
        qs = LoreEntry.objects.filter(status=LoreEntry.Status.PUBLISHED).order_by("-created_at")
        total = qs.count()
        if total == 0:
            caller.msg("The lore compendium is empty.")
            return

        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = max(1, min(page, total_pages))
        start = (page - 1) * _PAGE_SIZE
        entries = list(qs[start : start + _PAGE_SIZE])

        lines = [
            f"|w== Lore Compendium ==|n (page {page}/{total_pages}, {total} entries)",
            "-" * 50,
        ]
        for e in entries:
            tags_str = " ".join(f"|c[{t.name}]|n" for t in e.tags.all()[:3]) or ""
            lock_badge = " |r[RESTRICTED]|n" if e.privacy == LoreEntry.Privacy.RESTRICTED else ""
            lines.append(f"  |w#{e.entry_number}|n {e.title}{lock_badge}{_web_link(e)} {tags_str}")
            if e.summary:
                lines.append(f"      {e.summary[:80]}{'...' if len(e.summary) > 80 else ''}")
        lines.append("-" * 50)
        if total_pages > 1:
            lines.append(
                "Use |w+lore <page#>|n to navigate. Use |w+lore/read #N|n to read an entry."
            )
        caller.msg("\n".join(lines))

    def _do_read(self, arg):
        caller = self.caller
        entry, err = _resolve_entry(arg, caller)
        if err:
            caller.msg(err)
            return

        if entry.privacy == LoreEntry.Privacy.RESTRICTED and not entry.is_accessible_to(caller):
            tags_str = ", ".join(t.name for t in entry.tags.all()) or "none"
            caller.msg(
                f"|w== #{entry.entry_number}: {entry.title} ==|n\n"
                f"|r[RESTRICTED]|n — Full contents require a storyteller to share this with you.\n"
                f"Tags: {tags_str}\n"
                + (f"Hint: {entry.summary}" if entry.summary else "(No hint available.)")
            )
            return

        tags_str = ", ".join(t.name for t in entry.tags.all()) or "none"
        # Region display via soft-ref bridge
        region_ids = LoreRegionLink.objects.filter(entry=entry).values_list("region_id", flat=True)
        regions_str = "none"
        try:
            Region = _get_model("LORE_REGIONS_APP_LABEL", "Region", "regions")
            regions_str = (
                ", ".join(
                    Region.objects.filter(pk__in=list(region_ids))
                    .order_by("name")
                    .values_list("name", flat=True)
                )
                or "none"
            )
        except Exception:
            pass

        lines = [
            f"|w== #{entry.entry_number}: {entry.title} ==|n{_web_link(entry)}",
            f"Author: {entry.author_name} | Tags: {tags_str} | Regions: {regions_str}",
            f"Written: {entry.created_at.strftime('%Y-%m-%d')}",
            "-" * 50,
            entry.body if entry.body else "|x(No content yet.)|n",
            "-" * 50,
        ]
        if entry.summary:
            lines.append(f"|wSummary:|n {entry.summary}")
        if is_staff(caller) and entry.is_flagged:
            lines.append(f"|r[FLAGGED]|n {entry.flag_reason}")
        caller.msg("\n".join(lines))

    def _do_search(self, term):
        caller = self.caller
        qs = (
            LoreEntry.objects.filter(status=LoreEntry.Status.PUBLISHED).filter(
                title__icontains=term
            )
        ) | (
            LoreEntry.objects.filter(status=LoreEntry.Status.PUBLISHED).filter(body__icontains=term)
        )
        entries = list(qs.distinct().order_by("-created_at")[:20])
        if not entries:
            caller.msg(f"No lore entries found matching '{term}'.")
            return
        lines = [f"|wSearch results for '{term}':|n"]
        for e in entries:
            lines.append(_format_entry_row(e))
        caller.msg("\n".join(lines))

    def _do_submit(self, title, scene_arg=None):
        caller = self.caller
        if LoreEntry.objects.filter(
            title__iexact=title, status=LoreEntry.Status.PUBLISHED
        ).exists():
            caller.msg(
                f"|rA PUBLISHED entry titled '{title}' already exists.|n " f"Use a different title."
            )
            return
        caller.ndb._lore_submit_ctx = {"title": title, "scene_arg": scene_arg}
        self.start_new_edit(_lore_submit_save)

    def _do_edit(self, arg):
        caller = self.caller
        entry, err = _resolve_entry(arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("You can only edit your own lore entries.")
            return
        self.start_edit(entry, field_name="body", version_model_class=LoreVersion)

    def _do_tag(self, entry_arg, tag_name, make_major=False):
        caller = self.caller
        if make_major and not is_staff(caller):
            caller.msg("Only staff can create major tags.")
            return
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can add tags.")
            return
        tag, created = LoreTag.objects.get_or_create(
            name__iexact=tag_name,
            defaults={
                "name": tag_name,
                "is_major": make_major,
                "created_by": caller,
                "created_by_name": caller.key,
            },
        )
        if not created and make_major and not tag.is_major:
            tag.is_major = True
            tag.save(update_fields=["is_major"])
            caller.msg(f"Tag '{tag.name}' upgraded to major.")
        entry.tags.add(tag)
        action = "created and added" if created else "added"
        caller.msg(f"|gTag '{tag.name}' {action} to #{entry.entry_number}.|n")

    def _do_untag(self, entry_arg, tag_name):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can remove tags.")
            return
        try:
            tag = LoreTag.objects.get(name__iexact=tag_name)
        except LoreTag.DoesNotExist:
            caller.msg(f"Tag '{tag_name}' not found.")
            return
        entry.tags.remove(tag)
        caller.msg(f"Removed tag '{tag.name}' from #{entry.entry_number}.")

    def _do_region(self, entry_arg, region_name):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can associate regions.")
            return
        try:
            Region = _get_model("LORE_REGIONS_APP_LABEL", "Region", "regions")
            region = Region.objects.get(name__iexact=region_name)
        except Exception:
            caller.msg(f"No region named '{region_name}' found.")
            return
        _, created = LoreRegionLink.objects.get_or_create(
            entry=entry,
            region_id=region.pk,
            defaults={"created_by": caller, "created_by_name": caller.key},
        )
        if created:
            caller.msg(f"|gLinked region '{region.name}' to #{entry.entry_number}.|n")
        else:
            caller.msg(f"Region '{region.name}' is already linked to #{entry.entry_number}.")

    def _do_unregion(self, entry_arg, region_name):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can modify region associations.")
            return
        try:
            Region = _get_model("LORE_REGIONS_APP_LABEL", "Region", "regions")
            region = Region.objects.get(name__iexact=region_name)
        except Exception:
            caller.msg(f"No region named '{region_name}' found.")
            return
        deleted, _ = LoreRegionLink.objects.filter(entry=entry, region_id=region.pk).delete()
        if deleted:
            caller.msg(f"Removed region '{region.name}' from #{entry.entry_number}.")
        else:
            caller.msg(f"Region '{region.name}' is not linked to #{entry.entry_number}.")

    def _do_object(self, entry_arg, obj_ref):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can tag objects.")
            return
        target = caller.search(obj_ref, global_search=True)
        if not target:
            return
        entry.objects_tagged.add(target)
        caller.msg(f"|gTagged '{target.key}' on #{entry.entry_number}.|n")

    def _do_unobject(self, entry_arg, obj_ref):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can modify object tags.")
            return
        target = caller.search(obj_ref, global_search=True)
        if not target:
            return
        entry.objects_tagged.remove(target)
        caller.msg(f"Removed '{target.key}' from #{entry.entry_number}.")

    def _do_link_scene(self, entry_arg, scene_arg):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can link scenes.")
            return
        if not scene_arg.isdigit():
            caller.msg("Scene ID must be an integer.")
            return
        try:
            Scene = _get_model("LORE_SCENES_APP_LABEL", "Scene", "scenes")
            scene = Scene.objects.get(pk=int(scene_arg))
        except Exception:
            caller.msg(f"No scene #{scene_arg} found.")
            return
        _, created = LoreSceneLink.objects.get_or_create(
            entry=entry,
            scene_id=scene.pk,
            defaults={"created_by": caller, "created_by_name": caller.key},
        )
        if created:
            caller.msg(f"|gLinked scene #{scene_arg} to entry #{entry.entry_number}.|n")
        else:
            caller.msg(f"Scene #{scene_arg} is already linked to #{entry.entry_number}.")

    def _do_link_plot(self, entry_arg, plot_arg):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not _can_edit_entry(entry, caller):
            caller.msg("Only the entry author (or staff) can link plot threads.")
            return
        plot_arg = plot_arg.lstrip("#")
        if not plot_arg.isdigit():
            caller.msg("Plot thread ID must be an integer (e.g. #5 or 5).")
            return
        try:
            PlotThread = _get_model("LORE_PLOTS_APP_LABEL", "PlotThread", "plots")
            thread = PlotThread.objects.get(plot_number=int(plot_arg))
        except Exception:
            caller.msg(f"No plot thread #{plot_arg} found.")
            return
        _, created = PlotLoreLink.objects.get_or_create(
            thread_id=thread.pk,
            entry=entry,
            defaults={"created_by": caller, "created_by_name": caller.key},
        )
        if created:
            caller.msg(
                f"|gLinked entry #{entry.entry_number} to plot thread #{thread.plot_number}.|n"
            )
        else:
            caller.msg(f"Entry #{entry.entry_number} is already linked to #{thread.plot_number}.")

    def _do_approve(self, arg):
        caller = self.caller
        entry, err = _resolve_entry(arg, caller)
        if err:
            caller.msg(err)
            return
        if entry.status != LoreEntry.Status.SUBMITTED:
            caller.msg(
                f"Entry #{entry.entry_number} is {entry.get_status_display()}, not Submitted."
            )
            return
        entry.publish(reviewed_by=caller)
        caller.msg(f"|gEntry #{entry.entry_number} '{entry.title}' approved and published.|n")

    def _do_reject(self, entry_arg, reason):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if entry.status not in (LoreEntry.Status.SUBMITTED, LoreEntry.Status.DRAFT):
            caller.msg(
                f"Entry #{entry.entry_number} is {entry.get_status_display()} — cannot reject."
            )
            return
        entry.reject(reviewed_by=caller)
        caller.msg(
            f"|yEntry #{entry.entry_number} '{entry.title}' rejected and archived.|n"
            + (f"\nReason: {reason}" if reason else "")
        )

    def _do_flag(self, entry_arg, reason):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if entry.is_flagged:
            caller.msg(f"Entry #{entry.entry_number} is already flagged.")
            return
        entry.flag(flagged_by=caller, reason=reason)
        caller.msg(
            f"|yEntry #{entry.entry_number} flagged for staff review.|n"
            + (f" Reason: {reason}" if reason else "")
        )

    def _do_unflag(self, arg):
        caller = self.caller
        entry, err = _resolve_entry(arg, caller)
        if err:
            caller.msg(err)
            return
        if not entry.is_flagged:
            caller.msg(f"Entry #{entry.entry_number} is not flagged.")
            return
        entry.unflag()
        caller.msg(f"|gEntry #{entry.entry_number} flag cleared.|n")

    def _do_history(self, arg):
        caller = self.caller
        entry, err = _resolve_entry(arg, caller)
        if err:
            caller.msg(err)
            return
        self.view_versions(entry, LoreVersion)

    def _do_diff(self, entry_arg, version_str):
        caller = self.caller
        entry, err = _resolve_entry(entry_arg, caller)
        if err:
            caller.msg(err)
            return
        if not version_str.isdigit():
            caller.msg("Version number must be an integer.")
            return
        self.view_diff(entry, LoreVersion, int(version_str), field_name="body")

    def _do_acquired(self):
        caller = self.caller
        acquisitions = (
            LoreAcquisition.objects.filter(character=caller)
            .select_related("entry")
            .order_by("-acquired_at")
        )
        if not acquisitions.exists():
            caller.msg("You have not yet acquired any lore entries.")
            return
        lines = ["|w== Your Acquired Lore ==|n"]
        for acq in acquisitions[:30]:
            e = acq.entry
            source_badge = f" |x[{acq.get_source_display()}]|n"
            lines.append(f"  |w#{e.entry_number}|n {e.title}{_web_link(e)}{source_badge}")
        count = acquisitions.count()
        if count > 30:
            lines.append(f"  ... and {count - 30} more. Visit the web compendium.")
        caller.msg("\n".join(lines))

    def _do_queue(self):
        entries = LoreEntry.objects.filter(status=LoreEntry.Status.SUBMITTED).order_by("created_at")
        if not entries.exists():
            self.caller.msg("No entries awaiting approval.")
            return
        lines = ["|w== Approval Queue ==|n"]
        for e in entries:
            flag_badge = " |r[FLAGGED]|n" if e.is_flagged else ""
            lines.append(
                f"  #{e.entry_number} {e.title} — by {e.author_name} "
                f"({e.created_at.strftime('%Y-%m-%d')}){flag_badge}"
            )
        lines.append("\nUse |w+lore/approve #N|n or |w+lore/reject #N=<reason>|n to action.")
        self.caller.msg("\n".join(lines))


def _lore_submit_save(caller, content):
    """Called by EditingMixin.start_new_edit when the user saves a new entry."""
    ctx = getattr(caller.ndb, "_lore_submit_ctx", None)
    title = ctx["title"] if ctx else "Untitled"
    scene_arg = ctx.get("scene_arg") if ctx else None
    caller.ndb._lore_submit_ctx = None

    entry = LoreEntry.create_entry(title=title, author=caller, body=content)

    if scene_arg and scene_arg.isdigit():
        try:
            Scene = _get_model("LORE_SCENES_APP_LABEL", "Scene", "scenes")
            scene = Scene.objects.get(pk=int(scene_arg))
            LoreSceneLink.objects.get_or_create(
                entry=entry,
                scene_id=scene.pk,
                defaults={"created_by": caller, "created_by_name": caller.key},
            )
            caller.msg(
                f"|gLore entry #{entry.entry_number} '{entry.title}' submitted "
                f"and linked to scene #{scene_arg}.|n\n"
                f"Status: {entry.get_status_display()}"
            )
            return
        except Exception:
            caller.msg(
                f"|yWarning: scene #{scene_arg} not found — entry submitted without scene link.|n"
            )

    caller.msg(
        f"|gLore entry #{entry.entry_number} '{entry.title}' submitted.|n\n"
        f"Status: {entry.get_status_display()}"
    )


# ---------------------------------------------------------------------------
# CmdInvestigate
# ---------------------------------------------------------------------------


class CmdInvestigate(MuxCommand):
    """
    Declare a lore investigation focus (lean).

    Usage:
        +investigate                       Show your current lean
        +investigate/theme <name>          Lean toward a major theme tag
        +investigate/tag <name>            Lean toward any tag
        +investigate/region <name>         Lean toward a region
        +investigate/entry <id>            Lean toward a specific entry
        +investigate/plot <id>             Lean toward a plot thread's lore
        +investigate/clear                 Clear your current lean

    Sets a persistent preference tilting your passive lore acquisition toward
    entries matching the specified topic.
    """

    key = "+investigate"
    aliases = ["+inv"]  # noqa: RUF012
    help_category = "Lore"
    locks = "cmd:all()"

    _VALID_TYPES = ("theme", "tag", "region", "entry", "plot")

    def func(self):
        sw = self.switches
        caller = self.caller
        args = self.args.strip()

        if not sw:
            return self._do_show()

        if "clear" in sw:
            caller.lore_lean_type = None
            caller.lore_lean_value = None
            caller.msg("Your lore lean has been cleared.")
            return

        for lean_type in self._VALID_TYPES:
            if lean_type in sw:
                value = args
                if not value:
                    caller.msg(f"Usage: |w+investigate/{lean_type} <value>|n")
                    return
                return self._do_set_lean(lean_type, value)

        caller.msg("Unknown switch. Valid lean types: theme, tag, region, entry, plot, clear.")

    def _do_show(self):
        caller = self.caller
        lean_type = caller.lore_lean_type
        lean_value = caller.lore_lean_value
        if not lean_type:
            caller.msg(
                "You have no active lore lean. Use |w+investigate/<type> <value>|n to set one."
            )
            return
        caller.msg(
            f"|wCurrent lean:|n {lean_type.capitalize()} — {lean_value}\n"
            f"Use |w+investigate/clear|n to remove it."
        )

    def _do_set_lean(self, lean_type, value):
        caller = self.caller

        if lean_type == "entry":
            val = value.lstrip("#")
            if not val.isdigit():
                caller.msg("Entry lean requires a numeric ID (e.g. +investigate/entry #12).")
                return
            entry, err = _resolve_entry(f"#{val}", caller)
            if err:
                caller.msg(err)
                return
            caller.lore_lean_type = lean_type
            caller.lore_lean_value = entry.entry_number
            caller.msg(
                f"|gLean set:|n investigating {lean_type} — #{entry.entry_number} {entry.title}"
            )
            return

        if lean_type == "plot":
            val = value.lstrip("#")
            if not val.isdigit():
                caller.msg("Plot lean requires a numeric ID (e.g. +investigate/plot #3).")
                return
            try:
                PlotThread = _get_model("LORE_PLOTS_APP_LABEL", "PlotThread", "plots")
                thread = PlotThread.objects.get(plot_number=int(val))
            except Exception:
                caller.msg(f"No plot thread #{val} found.")
                return
            caller.lore_lean_type = lean_type
            caller.lore_lean_value = thread.plot_number
            caller.msg(
                f"|gLean set:|n investigating {lean_type} — #{thread.plot_number} {thread.name}"
            )
            return

        if lean_type == "region":
            try:
                Region = _get_model("LORE_REGIONS_APP_LABEL", "Region", "regions")
                region = Region.objects.get(name__iexact=value)
            except Exception:
                caller.msg(f"No region named '{value}' found.")
                return
            caller.lore_lean_type = lean_type
            caller.lore_lean_value = region.name
            caller.msg(f"|gLean set:|n investigating {lean_type} — {region.name}")
            return

        if lean_type in ("theme", "tag"):
            filter_kwargs = {"name__iexact": value}
            if lean_type == "theme":
                filter_kwargs["is_major"] = True
            try:
                tag = LoreTag.objects.get(**filter_kwargs)
            except LoreTag.DoesNotExist:
                if lean_type == "theme":
                    caller.msg(
                        f"No major theme tag named '{value}' found. "
                        f"Use |w+investigate/tag|n for minor tags."
                    )
                else:
                    caller.msg(f"No tag named '{value}' found.")
                return
            caller.lore_lean_type = lean_type
            caller.lore_lean_value = tag.name
            caller.msg(f"|gLean set:|n investigating {lean_type} — {tag.name}")
            return

        caller.msg(f"Unknown lean type '{lean_type}'.")


# ---------------------------------------------------------------------------
# CmdShare
# ---------------------------------------------------------------------------


class CmdShare(MuxCommand):
    """
    Share a lore entry with another character.

    Usage:
        +share <character>=<id>

    Gives a lore entry you possess to another character. Creates a
    LoreAcquisition(source=SHARED) for the recipient.
    """

    key = "+share"
    aliases = []  # noqa: RUF012
    help_category = "Lore"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+share <character>=<id>|n")
            return

        target = caller.search(self.lhs.strip(), global_search=True)
        if not target:
            return

        if target == caller:
            caller.msg("You cannot share lore with yourself.")
            return

        entry, err = _resolve_entry(self.rhs.strip(), caller, require_published=True)
        if err:
            caller.msg(err)
            return

        if (
            not is_staff(caller)
            and not LoreAcquisition.objects.filter(entry=entry, character=caller).exists()
        ):
            caller.msg(f"You don't have '#{entry.entry_number} {entry.title}' in your compendium.")
            return

        from evennia_lore.signals import lore_acquired

        acq, created = LoreAcquisition.objects.get_or_create(
            entry=entry,
            character=target,
            defaults={
                "character_name": target.key,
                "source": LoreAcquisition.Source.SHARED,
                "shared_by": caller,
                "shared_by_name": caller.key,
            },
        )

        if not created:
            caller.msg(
                f"{target.key} already has '#{entry.entry_number} {entry.title}' "
                f"in their compendium."
            )
            return

        lore_acquired.send(
            sender=LoreAcquisition,
            acquisition=acq,
            entry=entry,
            character=target,
            shared_by=caller,
        )
        caller.msg(f"|gShared '#{entry.entry_number} {entry.title}' with {target.key}.|n")
        target.msg(
            f"|y[Lore]|n {caller.key} has shared a lore entry with you: "
            f"|w{entry.title}|n (#{entry.entry_number}). "
            f"Use |w+lore/read #{entry.entry_number}|n to read it."
        )


# ---------------------------------------------------------------------------
# CmdHint
# ---------------------------------------------------------------------------


class CmdHint(MuxCommand):
    """
    Reveal hints for restricted lore in your current location.

    Usage:
        +hint [topic]

    Shows the summary/hint text for RESTRICTED lore entries linked to
    your current room or region. Optional topic filters by tag name.
    """

    key = "+hint"
    aliases = []  # noqa: RUF012
    help_category = "Lore"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        topic = self.args.strip().lower()

        room = caller.location
        if not room:
            caller.msg("You are not in a room.")
            return

        qs = LoreEntry.objects.filter(
            status=LoreEntry.Status.PUBLISHED,
            privacy=LoreEntry.Privacy.RESTRICTED,
        )

        room_entries = qs.filter(rooms=room)

        # Region-linked entries — gated on regions app being present
        region_entries = LoreEntry.objects.none()
        try:
            from django.apps import apps as django_apps

            regions_label = getattr(settings, "LORE_REGIONS_APP_LABEL", "regions")
            RegionMembership = django_apps.get_model(regions_label, "RegionMembership")
            membership = RegionMembership.objects.filter(room=room).first()
            if membership:
                region_entry_ids = LoreRegionLink.objects.filter(
                    region_id=membership.region_id
                ).values_list("entry_id", flat=True)
                region_entries = qs.filter(pk__in=region_entry_ids)
        except Exception:
            pass

        combined = (room_entries | region_entries).distinct()

        if topic:
            combined = combined.filter(tags__name__icontains=topic)

        entries = list(combined.order_by("entry_number"))
        if not entries:
            msg = "No restricted lore hints found"
            if topic:
                msg += f" matching '{topic}'"
            msg += " in this area."
            caller.msg(msg)
            return

        lines = ["|w== Lore Hints ==|n (restricted entries — ask a storyteller to +share)"]
        for e in entries:
            tags_str = ", ".join(t.name for t in e.tags.all()) or "none"
            lines.append(f"\n|w{e.title}|n [#{e.entry_number}]")
            lines.append(f"  Tags: {tags_str}")
            lines.append(f"  Hint: {e.summary}" if e.summary else "  Hint: (No hint text.)")
        caller.msg("\n".join(lines))


# ---------------------------------------------------------------------------
# CmdForget
# ---------------------------------------------------------------------------


class CmdForget(MuxCommand):
    """
    Remove a lore entry from your compendium.

    Usage:
        +forget <id>

    Deletes your LoreAcquisition for this entry so you can re-discover it
    later. Useful for testing passive trickle or for IC memory-loss RP.
    The entry itself is not deleted.
    """

    key = "+forget"
    aliases = []  # noqa: RUF012
    help_category = "Lore"
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        arg = self.args.strip()
        if not arg:
            caller.msg("Usage: |w+forget <id>|n")
            return

        entry, err = _resolve_entry(arg, caller, require_published=True)
        if err:
            caller.msg(err)
            return

        deleted, _ = LoreAcquisition.objects.filter(entry=entry, character=caller).delete()
        if deleted:
            caller.msg(
                f"You have forgotten '#{entry.entry_number} {entry.title}'. "
                f"You may re-acquire it passively."
            )
        else:
            caller.msg(f"You don't have '#{entry.entry_number} {entry.title}' in your compendium.")
