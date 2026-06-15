# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Scene lifecycle and log management commands for evennia_scenes.

Provides CmdScene (+scene) and CmdLog (+log). Add both to your
CharacterCmdSet::

    from evennia_scenes.commands import CmdScene, CmdLog

Settings:
    SCENES_STAFF_LOCK — lock string for staff operations (default
        "cmd:perm(Builder)").
    SITE_URL          — optional absolute URL base for web links (e.g.
        "https://mygame.com"). When absent, relative URLs are emitted
        (suitable for the webclient; MXP telnet clients need the full URL).
"""

from django.conf import settings
from evennia.commands.default.muxcommand import MuxCommand
from evennia.utils.eveditor import EvEditor

from evennia_links import EditingMixin
from evennia_scenes.models import LogEntry, LogEntryVersion, Scene, SceneParticipant
from evennia_scenes.signals import scene_closed, scene_opened

# How many log entries to show per page in +log.
LOG_ENTRIES_PER_PAGE = 20

try:
    from evennia_accessibility.utils import uses_screenreader
except ImportError:

    def uses_screenreader(_):
        return False


def _is_staff(character):
    """Check if character has staff permissions via SCENES_STAFF_LOCK setting."""
    lock_expr = getattr(settings, "SCENES_STAFF_LOCK", "cmd:perm(Builder)")
    expr = lock_expr[4:] if lock_expr.startswith("cmd:") else lock_expr
    try:
        return bool(character.locks.check_lockstring(character, expr))
    except Exception:
        return False


def _is_scene_owner(character, scene):
    """Check if the character created the scene or is staff."""
    return scene.creator == character or _is_staff(character)


def _scene_web_path(pk):
    """Return a relative or absolute URL for a scene's web page.

    Uses SITE_URL if set (for MXP telnet clients); falls back to a
    relative path suitable for the webclient.
    """
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    return f"{base}/scenes/{pk}/"


# ---------------------------------------------------------------------------
# +scene/desc EvEditor callbacks
# ---------------------------------------------------------------------------


def _desc_load(caller):
    """Load the scene description into the editor."""
    ctx = caller.ndb._scene_desc_context
    if not ctx:
        return ""
    try:
        scene = Scene.all_objects.get(pk=ctx["scene_pk"])
    except Scene.DoesNotExist:
        caller.msg("|rError: the scene no longer exists.|n")
        return ""
    return scene.description


def _desc_save(caller, buffer):
    """Save the editor buffer to the scene description."""
    ctx = caller.ndb._scene_desc_context
    if not ctx:
        caller.msg("|rError: no scene editing context found.|n")
        return False
    try:
        scene = Scene.all_objects.get(pk=ctx["scene_pk"])
    except Scene.DoesNotExist:
        caller.msg("|rError: the scene no longer exists.|n")
        return False
    scene.description = buffer.strip()
    scene.save(update_fields=["description"])
    caller.msg("Scene description saved.")
    return True


def _desc_quit(caller):
    """Clean up the scene description editing context."""
    caller.ndb._scene_desc_context = None
    caller.msg("Description editor closed.")


class CmdScene(MuxCommand):
    """
    Manage scenes in the current room.

    Usage:
        +scene                              - View current scene or list recent
        +scene/open [<title>]               - Open a new scene in this room
        +scene/close                        - Close (pause) the active scene
        +scene/resume [<id>]                - Resume a closed scene
        +scene/title <text>                 - Set or change the scene title
        +scene/desc                         - Edit scene description (EvEditor)
        +scene/privacy <public|pose-private|view-private>
                                            - Set scene privacy tier
        +scene/invite <character>           - Invite a character to pose
        +scene/join                         - Join the active scene
        +scene/leave                        - Leave the active scene
        +scene/info [<id>]                  - View scene details

    Privacy tiers:
        public       - Anyone can view on the web; anyone in the room can pose.
        pose-private - Anyone can view on the web; only invited characters can
                       pose. Use +scene/invite to add characters.
        view-private - Only invited characters (and staff) can view or pose.

    Scenes represent active RP sessions. Closed public and pose-private scenes
    appear automatically on the web log browser — no separate publish step is
    needed. Scenes can be paused (closed) and resumed multiple times.
    """

    key = "+scene"
    aliases: list = []  # noqa: RUF012
    help_category = "Scenes"
    locks = "cmd:all()"

    def func(self):
        """Route to the appropriate switch handler."""
        caller = self.caller

        if not caller.location:
            caller.msg("You have no location.")
            return

        if not self.switches:
            self._show_status()
            return

        switch = self.switches[0].lower()
        handler = {
            "open": self._open,
            "close": self._close,
            "resume": self._resume,
            "title": self._title,
            "desc": self._desc,
            "privacy": self._privacy,
            "invite": self._invite,
            "join": self._join,
            "leave": self._leave,
            "info": self._info,
            "publish": self._publish,
        }.get(switch)

        if handler:
            handler()
        else:
            caller.msg(f"|rUnknown switch:|n /{switch}. See |whelp +scene|n for usage.")

    # --- Switch handlers ---------------------------------------------------

    def _show_status(self):
        """Show the current room's scene or list recent scenes."""
        caller = self.caller
        room = caller.location
        scene = self._get_active_scene()

        if scene:
            caller.msg(self._format_scene_brief(scene))
        else:
            recent = Scene.all_objects.filter(room=room).order_by("-created_at")[:3]
            if recent:
                lines = ["|wRecent scenes in this room:|n"]
                for s in recent:
                    title = s.title or "Untitled"
                    lines.append(
                        f"  |lc+scene/info {s.pk}|lt#{s.pk}|le "
                        f"|lu{_scene_web_path(s.pk)}|lt[↗]|le "
                        f"{title} ({s.get_status_display()}) — "
                        f"{s.created_at.strftime('%Y-%m-%d')}"
                    )
                caller.msg("\n".join(lines))
            else:
                caller.msg("No active scene in this room. Use |w+scene/open|n to start one.")

    def _open(self):
        """Open a new scene in this room."""
        caller = self.caller
        room = caller.location

        # room_type is a game convention for IC/OOC room classification.
        room_type = getattr(room, "room_type", "ic") or "ic"
        if room_type != "ic":
            caller.msg("Scenes can only be opened in IC rooms.")
            return

        existing = self._get_active_scene()
        if existing:
            title = existing.title or "Untitled"
            caller.msg(
                f"This room already has an active scene: "
                f"|w{title}|n (#{existing.pk}). "
                f"Close it first with |w+scene/close|n."
            )
            return

        title = self.args.strip() if self.args else ""

        scene = Scene.objects.create(
            title=title,
            room=room,
            room_name=room.key,
            creator=caller,
            creator_name=caller.key,
        )
        room.active_scene_id = scene.pk

        SceneParticipant.objects.create(
            scene=scene,
            character=caller,
            character_name=caller.key,
        )

        LogEntry.create_entry(
            scene=scene,
            author=None,
            content=f"Scene opened by {caller.key}.",
            log_type="system",
        )

        scene_opened.send(sender=Scene, scene=scene, creator=caller)

        title_str = f' "{title}"' if title else ""
        room.msg_contents(f"|y{caller.key} has opened a scene{title_str}.|n")

    def _close(self):
        """Close (pause) the active scene."""
        caller = self.caller
        room = caller.location
        scene = self._get_active_scene()

        if not scene:
            caller.msg("There is no active scene in this room.")
            return

        if not _is_scene_owner(caller, scene):
            caller.msg("Only the scene creator or staff can close a scene.")
            return

        LogEntry.create_entry(
            scene=scene,
            author=None,
            content=f"Scene closed by {caller.key}.",
            log_type="system",
        )

        scene.close(closer=caller)
        room.active_scene_id = None

        scene.participants.filter(is_active=True).update(is_active=False)

        scene_closed.send(sender=Scene, scene=scene, closer=caller)

        room.msg_contents(f"|y{caller.key} has closed the scene.|n")

    def _resume(self):
        """Resume a closed scene."""
        caller = self.caller
        room = caller.location

        existing = self._get_active_scene()
        if existing:
            caller.msg(
                f"This room already has an active scene (#{existing.pk}). " f"Close it first."
            )
            return

        if self.args and self.args.strip().isdigit():
            scene_id = int(self.args.strip())
            try:
                scene = Scene.objects.get(pk=scene_id, status=Scene.Status.CLOSED)
            except Scene.DoesNotExist:
                caller.msg(f"No closed scene found with ID #{scene_id}.")
                return
        else:
            scene = (
                Scene.objects.filter(room=room, status=Scene.Status.CLOSED)
                .order_by("-ended_at")
                .first()
            )
            if not scene:
                caller.msg("No closed scenes found in this room to resume.")
                return

        if not _is_scene_owner(caller, scene):
            caller.msg("Only the scene creator or staff can resume a scene.")
            return

        scene.resume()
        room.active_scene_id = scene.pk

        # Re-activate participants who are currently in the room.
        # has_account is Evennia's standard check for player-controlled objects.
        chars_in_room = [obj for obj in room.contents if obj.has_account]
        for char in chars_in_room:
            participant, created = SceneParticipant.objects.get_or_create(
                scene=scene,
                character=char,
                defaults={"character_name": char.key},
            )
            if not created and not participant.is_active:
                participant.rejoin()

        LogEntry.create_entry(
            scene=scene,
            author=None,
            content=f"Scene resumed by {caller.key}.",
            log_type="system",
        )

        title = scene.title or "Untitled"
        room.msg_contents(f'|y{caller.key} has resumed scene "{title}" (#{scene.pk}).|n')

    def _title(self):
        """Set or change the scene title."""
        caller = self.caller
        scene = self._get_active_scene()

        if not scene:
            caller.msg("There is no active scene in this room.")
            return

        if not _is_scene_owner(caller, scene):
            caller.msg("Only the scene creator or staff can set the title.")
            return

        if not self.args or not self.args.strip():
            caller.msg("Usage: |w+scene/title <text>|n")
            return

        title = self.args.strip()
        scene.title = title
        scene.save(update_fields=["title"])

        caller.location.msg_contents(f"|yScene title set to:|n {title}")

    def _desc(self):
        """Edit the scene description via EvEditor."""
        caller = self.caller
        scene = self._get_active_scene()

        if not scene and self.args and self.args.strip().isdigit():
            scene_id = int(self.args.strip())
            try:
                scene = Scene.all_objects.get(pk=scene_id)
            except Scene.DoesNotExist:
                caller.msg(f"No scene found with ID #{scene_id}.")
                return

        if not scene:
            caller.msg("There is no active scene in this room.")
            return

        if not _is_scene_owner(caller, scene):
            caller.msg("Only the scene creator or staff can edit the description.")
            return

        if getattr(caller.ndb, "_scene_desc_context", None):
            caller.msg(
                "You already have a description editor open. "
                "Finish or quit it first (|w:q|n or |w:wq|n)."
            )
            return

        caller.ndb._scene_desc_context = {"scene_pk": scene.pk}

        EvEditor(
            caller,
            loadfunc=_desc_load,
            savefunc=_desc_save,
            quitfunc=_desc_quit,
            key="scene_desc_editor",
            persistent=False,
        )

    def _privacy(self):
        """Set scene privacy."""
        caller = self.caller
        scene = self._get_active_scene()

        if not scene:
            caller.msg("There is no active scene in this room.")
            return

        if not _is_scene_owner(caller, scene):
            caller.msg("Only the scene creator or staff can set privacy.")
            return

        PRIVACY_MAP = {
            "public": Scene.Privacy.PUBLIC,
            "pose-private": Scene.Privacy.POSE_PRIVATE,
            "pose": Scene.Privacy.POSE_PRIVATE,
            "view-private": Scene.Privacy.VIEW_PRIVATE,
            "private": Scene.Privacy.VIEW_PRIVATE,
        }
        arg = self.args.strip().lower() if self.args else ""
        privacy_value = PRIVACY_MAP.get(arg)
        if privacy_value is None:
            caller.msg("Usage: |w+scene/privacy <public|pose-private|view-private>|n")
            return

        scene.privacy = privacy_value
        scene.save(update_fields=["privacy"])

        caller.location.msg_contents(f"|yScene privacy set to:|n {scene.get_privacy_display()}")

    def _invite(self):
        """Invite a character to pose in a non-public scene."""
        caller = self.caller
        scene = self._get_active_scene()

        if not scene:
            caller.msg("There is no active scene in this room.")
            return

        if not _is_scene_owner(caller, scene):
            caller.msg("Only the scene creator or staff can invite characters.")
            return

        if scene.privacy == Scene.Privacy.PUBLIC:
            caller.msg(
                "This scene is public — anyone in the room can pose. "
                "Use |w+scene/privacy pose-private|n first if you want "
                "to restrict posing to invited characters."
            )
            return

        target_name = self.args.strip() if self.args else ""
        if not target_name:
            caller.msg("Usage: |w+scene/invite <character>|n")
            return

        target = caller.search(target_name, quiet=True)
        if not target:
            caller.msg(f"Could not find a character named '{target_name}'.")
            return
        if isinstance(target, list):
            target = target[0]

        participant, _created = SceneParticipant.objects.get_or_create(
            scene=scene,
            character=target,
            defaults={"character_name": target.key, "is_active": False},
        )
        if not participant.is_invited:
            participant.is_invited = True
            participant.save(update_fields=["is_invited"])

        title = scene.title or "Untitled"
        caller.msg(f'|g{target.key} is now invited to pose in "{title}".|n')
        if target.has_account:
            target.msg(
                f"|g{caller.key} has invited you to pose in scene " f'"{title}" (#{scene.pk}).|n'
            )

    def _join(self):
        """Join the active scene as a participant."""
        caller = self.caller
        scene = self._get_active_scene()

        if not scene:
            caller.msg("There is no active scene in this room.")
            return

        if scene.privacy in (Scene.Privacy.POSE_PRIVATE, Scene.Privacy.VIEW_PRIVATE):
            already_invited = SceneParticipant.objects.filter(
                scene=scene, character=caller, is_invited=True
            ).exists()
            if not already_invited and not _is_scene_owner(caller, scene):
                caller.msg(
                    "This scene is invite-only. Ask the scene creator "
                    "for an invite via |w+scene/invite|n."
                )
                return

        participant, created = SceneParticipant.objects.get_or_create(
            scene=scene,
            character=caller,
            defaults={"character_name": caller.key},
        )

        if created:
            caller.location.msg_contents(f"|y{caller.key} has joined the scene.|n")
        elif not participant.is_active:
            participant.rejoin()
            caller.location.msg_contents(f"|y{caller.key} has rejoined the scene.|n")
        else:
            caller.msg("You are already in this scene.")

    def _leave(self):
        """Leave the active scene."""
        caller = self.caller
        scene = self._get_active_scene()

        if not scene:
            caller.msg("There is no active scene in this room.")
            return

        try:
            participant = SceneParticipant.objects.get(scene=scene, character=caller)
        except SceneParticipant.DoesNotExist:
            caller.msg("You are not in this scene.")
            return

        if not participant.is_active:
            caller.msg("You have already left this scene.")
            return

        participant.leave()
        caller.location.msg_contents(f"|y{caller.key} has left the scene.|n")

    def _info(self):
        """Show scene details."""
        caller = self.caller

        if self.args and self.args.strip().isdigit():
            scene_id = int(self.args.strip())
            try:
                scene = Scene.all_objects.get(pk=scene_id)
            except Scene.DoesNotExist:
                caller.msg(f"No scene found with ID #{scene_id}.")
                return
        else:
            scene = self._get_active_scene()
            if not scene:
                caller.msg("No active scene. Use |w+scene/info <id>|n to view a specific scene.")
                return

        if scene.privacy == Scene.Privacy.VIEW_PRIVATE and not _is_staff(caller):
            is_invited = SceneParticipant.objects.filter(
                scene=scene, character=caller, is_invited=True
            ).exists()
            if not is_invited:
                caller.msg("That scene is private.")
                return

        caller.msg(self._format_scene_detail(scene))

    def _publish(self):
        """Redirect to the privacy model (publish step no longer needed)."""
        self.caller.msg(
            "|yScenes no longer require a separate publish step.|n\n"
            "Closed |wpublic|n and |wpose-private|n scenes appear automatically "
            "on the web log browser when you close them.\n"
            "Use |w+scene/privacy|n to control visibility:\n"
            "  |w+scene/privacy public|n       — visible to everyone (default)\n"
            "  |w+scene/privacy pose-private|n — visible to everyone; "
            "only invited characters can pose\n"
            "  |w+scene/privacy view-private|n — only invited characters "
            "can view or pose"
        )

    # --- Helpers -----------------------------------------------------------

    def _get_active_scene(self):
        """Get the active scene in the caller's room, or None."""
        room = self.caller.location
        scene_id = getattr(room, "active_scene_id", None)
        if not scene_id:
            return None
        try:
            return Scene.objects.get(
                pk=scene_id,
                status__in=(Scene.Status.OPEN, Scene.Status.ACTIVE),
            )
        except Scene.DoesNotExist:
            room.active_scene_id = None
            return None

    @staticmethod
    def _format_scene_brief(scene):
        """Format a brief scene status display."""
        title = scene.title or "Untitled"
        participant_count = scene.participants.filter(is_active=True).count()
        entry_count = scene.log_entries.filter(is_deleted=False).count()
        return (
            f"|wActive Scene:|n {title} (#{scene.pk})\n"
            f"  Status: {scene.get_status_display()} | "
            f"Privacy: {scene.get_privacy_display()}\n"
            f"  Participants: {participant_count} | "
            f"Log entries: {entry_count}\n"
            f"  Use |w+scene/info|n for details, "
            f"|w+scene/close|n to pause."
        )

    @staticmethod
    def _format_scene_detail(scene):
        """Format a detailed scene info display."""
        title = scene.title or "Untitled"
        lines = [
            f"|wScene #{scene.pk}: {title}|n",
            f"  Status: {scene.get_status_display()} | " f"Privacy: {scene.get_privacy_display()}",
            f"  Room: {scene.room_name}",
            f"  Creator: {scene.creator_name}",
            f"  Created: {scene.created_at.strftime('%Y-%m-%d %H:%M')}",
        ]
        if scene.description:
            lines.append(f"  Description: {scene.description}")
        if scene.started_at:
            lines.append(f"  Started: {scene.started_at.strftime('%Y-%m-%d %H:%M')}")
        if scene.ended_at:
            lines.append(f"  Ended: {scene.ended_at.strftime('%Y-%m-%d %H:%M')}")

        participants = scene.participants.all()
        if participants:
            lines.append("  |wParticipants:|n")
            for p in participants:
                status = "active" if p.is_active else "left"
                invited_tag = " |g[invited]|n" if p.is_invited else ""
                lines.append(
                    f"    {p.character_name}{invited_tag} — " f"{p.pose_count} poses ({status})"
                )

        if scene.privacy != Scene.Privacy.PUBLIC:
            invited_absent = scene.participants.filter(
                is_invited=True, is_active=False, pose_count=0
            )
            if invited_absent.exists():
                names = ", ".join(p.character_name for p in invited_absent)
                lines.append(f"  |wInvited (not yet joined):|n {names}")

        entry_count = scene.log_entries.filter(is_deleted=False).count()
        lines.append(f"  Log entries: {entry_count}")

        if scene.status == Scene.Status.CLOSED:
            lines.append(
                f"  |lc+log {scene.pk}|lt[View Log]|le"
                f"  |lu{_scene_web_path(scene.pk)}|lt[↗ web]|le"
            )

        return "\n".join(lines)


class CmdLog(EditingMixin, MuxCommand):
    """
    View and edit scene logs.

    Usage:
        +log                          - List your recent scenes
        +log <scene_id>               - View a scene's log
        +log <scene_id>=<page>        - View a specific page
        +log/edit <entry_id>          - Edit a log entry (your own)
        +log/history <entry_id>       - View edit history
        +log/rollback <entry_id>=<ver> - Rollback to version (staff)
        +log/diff <entry_id>=<ver>    - View diff against version
        +log/ic <scene_id>            - Show only IC entries
        +log/ooc <scene_id>           - Show only OOC entries
    """

    key = "+log"
    aliases: list = []  # noqa: RUF012
    help_category = "Scenes"
    locks = "cmd:all()"

    def func(self):
        """Route to the appropriate handler."""
        caller = self.caller

        if not self.switches:
            if not self.args:
                self._list_recent()
            else:
                self._view_log()
            return

        switch = self.switches[0].lower()

        if switch == "edit":
            self._edit()
        elif switch == "history":
            self._history()
        elif switch == "rollback":
            self._rollback()
        elif switch == "diff":
            self._diff()
        elif switch in ("ic", "ooc", "all"):
            self._view_log(filter_type=switch)
        else:
            caller.msg(f"|rUnknown switch:|n /{switch}. See |whelp +log|n for usage.")

    # --- Handlers ----------------------------------------------------------

    def _list_recent(self):
        """List the caller's recent scenes."""
        caller = self.caller
        participations = (
            SceneParticipant.objects.filter(character=caller)
            .select_related("scene")
            .order_by("-scene__created_at")[:10]
        )

        if not participations:
            caller.msg("You haven't participated in any scenes yet.")
            return

        lines = ["|wYour Recent Scenes:|n"]
        lines.append("-" * 60)
        for p in participations:
            s = p.scene
            title = s.title or "Untitled"
            entry_count = s.log_entries.filter(is_deleted=False).count()
            lines.append(
                f"  |lc+log {s.pk}|lt#{s.pk}|le "
                f"|lu{_scene_web_path(s.pk)}|lt[↗]|le "
                f"{title} ({s.get_status_display()}) — "
                f"{s.created_at.strftime('%Y-%m-%d')} — "
                f"{entry_count} entries, {p.pose_count} poses"
            )
        lines.append("-" * 60)
        caller.msg("\n".join(lines))

    def _view_log(self, filter_type=None):
        """View a scene's log entries."""
        caller = self.caller

        args = self.args.strip() if self.args else ""
        if not args and self.lhs:
            args = self.lhs.strip()

        if not args:
            scene_id = getattr(caller.location, "active_scene_id", None)
            if not scene_id:
                caller.msg("Usage: |w+log <scene_id>|n")
                return
        else:
            if not args.isdigit():
                caller.msg("Usage: |w+log <scene_id>[=<page>]|n")
                return
            scene_id = int(args)

        page = 1
        if self.rhs and self.rhs.strip().isdigit():
            page = int(self.rhs.strip())

        try:
            scene = Scene.all_objects.get(pk=scene_id)
        except Scene.DoesNotExist:
            caller.msg(f"No scene found with ID #{scene_id}.")
            return

        if scene.privacy == Scene.Privacy.VIEW_PRIVATE and not _is_staff(caller):
            is_invited = SceneParticipant.objects.filter(
                scene=scene, character=caller, is_invited=True
            ).exists()
            if not is_invited:
                caller.msg("That scene is private.")
                return

        qs = scene.log_entries.filter(is_deleted=False)

        if filter_type == "ic":
            qs = qs.filter(
                log_type__in=[
                    LogEntry.LogType.POSE,
                    LogEntry.LogType.EMIT,
                    LogEntry.LogType.SAY,
                ]
            )
        elif filter_type == "ooc":
            qs = qs.filter(log_type__in=[LogEntry.LogType.OOC, LogEntry.LogType.WEB_OOC])

        total = qs.count()
        if total == 0:
            caller.msg("No log entries found.")
            return

        total_pages = (total + LOG_ENTRIES_PER_PAGE - 1) // LOG_ENTRIES_PER_PAGE
        page = max(1, min(page, total_pages))
        start = (page - 1) * LOG_ENTRIES_PER_PAGE
        entries = qs.order_by("order", "created_at")[start : start + LOG_ENTRIES_PER_PAGE]

        title = scene.title or "Untitled"
        lines = [f"|wScene #{scene.pk}: {title}|n " f"(page {page}/{total_pages})"]
        lines.append("-" * 68)

        for entry in entries:
            timestamp = entry.created_at.strftime("%H:%M")
            type_tag = self._format_type_tag(entry.log_type)
            lines.append(f"  {type_tag} [{timestamp}] " f"|w{entry.author_name}|n: {entry.content}")

        lines.append("-" * 68)
        if total_pages > 1:
            lines.append(
                f"Page {page}/{total_pages}. " f"Use |w+log {scene.pk}=<page>|n to navigate."
            )

        caller.msg("\n".join(lines))

    def _edit(self):
        """Edit a log entry via EvEditor."""
        caller = self.caller
        args = self.args.strip() if self.args else ""

        if not args or not args.isdigit():
            caller.msg("Usage: |w+log/edit <entry_id>|n")
            return

        try:
            entry = LogEntry.objects.get(pk=int(args), is_deleted=False)
        except LogEntry.DoesNotExist:
            caller.msg(f"No log entry found with ID #{args}.")
            return

        if entry.author != caller and not _is_staff(caller):
            caller.msg("You can only edit your own log entries.")
            return

        if entry.scene.is_archived:
            caller.msg("Cannot edit entries in an archived scene.")
            return

        self.start_edit(entry, "content", LogEntryVersion)

    def _history(self):
        """View edit history for a log entry."""
        caller = self.caller
        args = self.lhs.strip() if self.lhs else (self.args.strip() if self.args else "")

        if not args or not args.isdigit():
            caller.msg("Usage: |w+log/history <entry_id>[=<page>]|n")
            return

        try:
            entry = LogEntry.objects.get(pk=int(args))
        except LogEntry.DoesNotExist:
            caller.msg(f"No log entry found with ID #{args}.")
            return

        page = 1
        if self.rhs and self.rhs.strip().isdigit():
            page = int(self.rhs.strip())

        self.view_versions(entry, LogEntryVersion, page=page)

    def _rollback(self):
        """Rollback a log entry to a previous version (staff only)."""
        caller = self.caller

        if not _is_staff(caller):
            caller.msg("Only staff can rollback log entries.")
            return

        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+log/rollback <entry_id>=<version>|n")
            return

        lhs = self.lhs.strip()
        rhs = self.rhs.strip()

        if not lhs.isdigit() or not rhs.isdigit():
            caller.msg("Usage: |w+log/rollback <entry_id>=<version>|n")
            return

        try:
            entry = LogEntry.objects.get(pk=int(lhs))
        except LogEntry.DoesNotExist:
            caller.msg(f"No log entry found with ID #{lhs}.")
            return

        self.do_rollback(entry, LogEntryVersion, int(rhs))

    def _diff(self):
        """View a diff against a specific version."""
        caller = self.caller

        if not self.lhs or not self.rhs:
            caller.msg("Usage: |w+log/diff <entry_id>=<version>|n")
            return

        lhs = self.lhs.strip()
        rhs = self.rhs.strip()

        if not lhs.isdigit() or not rhs.isdigit():
            caller.msg("Usage: |w+log/diff <entry_id>=<version>|n")
            return

        try:
            entry = LogEntry.objects.get(pk=int(lhs))
        except LogEntry.DoesNotExist:
            caller.msg(f"No log entry found with ID #{lhs}.")
            return

        self.view_diff(entry, LogEntryVersion, int(rhs))

    # --- Helpers -----------------------------------------------------------

    @staticmethod
    def _format_type_tag(log_type):
        """Format a colored type tag for display."""
        tags = {
            "pose": "|G[pose]|n",
            "emit": "|G[emit]|n",
            "say": "|G[say] |n",
            "ooc": "|x[ooc] |n",
            "web_ooc": "|x[wooc]|n",
            "dice": "|C[dice]|n",
            "combat": "|R[cmbt]|n",
            "system": "|x[sys] |n",
        }
        return tags.get(log_type, f"[{log_type}]")
