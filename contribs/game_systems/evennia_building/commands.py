# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Room-context player commands; authorization and mutations live in services."""

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db.models import F, Q
from evennia.commands.default.muxcommand import MuxCommand
from evennia.objects.models import ObjectDB

from evennia_links.command_syntax import StrictSwitchMixin
from evennia_links.transactions import atomic_objects

from . import attachments, collaboration, frontier, services
from . import command_support as support
from .access import is_staff, ownership, require_revealed
from .models import (
    Frontier,
    FrontierRoom,
    GuestInvitation,
    PassageChange,
    ProjectAgreement,
    ProjectContributor,
    Property,
)
from .visibility import room_visibility


class BuildingCommand(StrictSwitchMixin, MuxCommand):
    """Validate the original switches before MuxCommand can ignore a bad one."""

    locks = "cmd:all()"
    help_category = "Building"

    def parse(self):
        """Keep the unfiltered switch list for strict, unique-prefix validation.

        MuxCommand's own matching would announce ambiguous or ignored switches,
        including staff-only names, before ``func`` refuses them.
        """
        # Match MuxCommand: switches start immediately after the command key.
        raw = self.args
        self.requested = (
            [value.lower() for value in raw.split(None, 1)[0][1:].split("/")]
            if raw.startswith("/") and len(raw.strip()) > 1
            else []
        )
        options, self.switch_options = self.switch_options, None
        try:
            super().parse()
        finally:
            self.switch_options = options
        self.switches = self.requested

    def func(self):
        """Report domain errors without dropping malformed syntax into another action."""
        try:
            require_revealed(self.caller)
            if len(self.requested) > 1:
                raise ValidationError(f"Use one switch at most. See help {self.key}.")
            self.switch = ""
            for value in self.requested:
                matches = [option for option in self.switch_options if option == value]
                if not matches:
                    matches = [option for option in self.switch_options if option.startswith(value)]
                if len(matches) != 1:
                    raise ValidationError(f"Choose one unambiguous switch. See help {self.key}.")
                self.switch = matches[0]
            self.execute()
        except (ValidationError, PermissionDenied, ObjectDoesNotExist, ValueError) as exc:
            if isinstance(exc, ValidationError):
                text = " ".join(exc.messages)
            elif isinstance(exc, ObjectDoesNotExist):
                # The default text names a model; never show players that.
                text = ""
            else:
                text = str(exc)
            self.caller.msg(text or f"Choose an available target. See help {self.key}.")

    @atomic_objects
    def execute(self):
        """Serialize preview validation and the service write in one transaction."""
        attachments.begin_write()
        ObjectDB.objects.filter(pk=self.caller.pk).update(db_key=F("db_key"))
        self.run()

    def bare(self, *, prose=False):
        """Read a target-less value, preserving literal punctuation in prose fields."""
        value = self.args.strip() if prose else self.lhs.strip()
        if value.startswith("=") or (not prose and self.rhs is not None):
            raise ValidationError(f"Use {self.key}/{self.switch} <value>, without '='.")
        return value

    def empty(self):
        """Refuse arguments on an action that takes none."""
        if self.args:
            raise ValidationError(f"Use {self.key}/{self.switch} without arguments.")

    def preview(self, action, state, token, command, text, *, suffix=""):
        """Print a complete preview and its exact confirmation command."""
        generated = support.confirm(self.caller, action, state, token)
        if generated:
            self.caller.msg(f"{text}\nConfirm within 15 minutes: {command}{generated}{suffix}")
            return False
        return True


class CmdBuildAdmin(BuildingCommand):
    """Review proposals and administer Building through one switch at a time.

    +buildadmin                       List pending submissions.
    +buildadmin <submission>           Inspect a frozen submission.
    +buildadmin/approve <submission>[=<token>] # <reason>
    +buildadmin/changes <submission>[=<token>] # <reason>
    +buildadmin/decline <submission>[=<token>] # <reason>
    +buildadmin/environment <submission>[=<token>] # <reason>
    +buildadmin/geometry <submission>[=<token>] # <reason>
    +buildadmin/policy <room>=<policy>  Set a room policy, or reset it.
    +buildadmin/region <region>=<policy>  Set a region policy, or reset it.
    +buildadmin/quiet                  Refresh and list quiet-review flags.
    +buildadmin/transfer <property>=<character> # <reason>
    +buildadmin/stock <return or transfer>  Set the draft's shop stock choice.
    +buildadmin/grants <clear or retain>  Set the draft's access-grant choice.
    +buildadmin/archive <property> # <reason>  Start a property archive plan.
    +buildadmin/children <yes or no>    Include affected apartments explicitly.
    +buildadmin/restore <property>[=<token>] # <reason>
    +buildadmin/retire <frontier> # <reason>  Start a frontier retirement plan.
    +buildadmin/frontiers [<areas>]    Set comma-listed additional frontier areas.
    +buildadmin/properties [<homes>]   Set comma-listed affected properties.
    +buildadmin/replacement <room>/<direction>=<room>  Set replacement passage.
    +buildadmin/unreplace <room>/<direction>  Remove a replacement connection.
    +buildadmin/frontierrestore <frontier>[=<token>] # <reason>
    +buildadmin/steward <room>=<character or none> # <reason>
    +buildadmin/passage <agreement>=<rooms> # <reason>  Draft replacement passage.
    +buildadmin/apply <change>[=<token>]  Apply passage after both owners agree.
    +buildadmin/reason <text>          Set the current draft's reason.
    +buildadmin/draft                  Inspect your persistent staff draft.
    +buildadmin/finish [<token>]        Preview the full draft, then confirm it.
    +buildadmin/cancel                 Abandon your staff draft.

    Policies accept open, residential, commercial, closed or reset. Reasons may
    follow policy changes after ' # '. Other mutation reasons are mandatory.
    Tokens expire after 15 minutes and bind the actor and affected records.
    Transfers default to clearing grants. A shop requires an explicit stock
    choice. Retirement and restoration retain all domain checks; owners accept
    replacement passage separately through +passage before staff applies it.
    """

    key = "+buildadmin"
    locks = "cmd:building_staff()"
    switch_options = (
        "list",
        "show",
        "approve",
        "changes",
        "decline",
        "environment",
        "geometry",
        "policy",
        "region",
        "quiet",
        "transfer",
        "stock",
        "grants",
        "archive",
        "children",
        "restore",
        "retire",
        "frontiers",
        "properties",
        "replacement",
        "unreplace",
        "frontierrestore",
        "steward",
        "passage",
        "apply",
        "reason",
        "draft",
        "finish",
        "cancel",
    )

    def run(self):
        """Keep staff authorization and dispatch separate from player commands."""
        from .staff_commands import run_staff

        run_staff(self)


class CmdBuild(BuildingCommand):
    """Draft a reviewed home from the room where you stand.

    +build                         List your projects.
    +build <project>               Inspect a project.
    +build/new <name>              Start an interior project.
    +build/enter <project>         Enter a draft.
    +build/room <room>             Move to a room within the current draft.
    +build/leave                   Leave a draft.
    +build/name <text>             Name the current room.
    +build/desc <text>             Describe the current room.
    +build/title <text>            Name the project or current interior boundary.
    +build/purpose <home or shop>  Set its purpose.
    +build/dig <direction>=<name>  Add a neighbouring room and both doors.
    +build/dig <name>              Begin an explicit room plan.
    +build/x <integer>             Set its x coordinate.
    +build/y <integer>             Set its y coordinate.
    +build/floor <integer>         Set its floor.
    +build/direction <direction>   Set its direction and neighbouring cell.
    +build/doorname <name>         Set its custom entrance door name.
    +build/back <name>             Set its custom return door name.
    +build/finish                  Create the planned room and both doors.
    +build/cancel                  Cancel the room plan.
    +build/door <room>[=<name>]    Join the current room to another draft room.
    +build/aliases <door>=<names>  Set a door's comma-listed aliases.
    +build/attach <room>=<name>    Choose the world attachment and entrance.
    +build/entrance <name>         Change the entrance label.
    +build/route <rooms>           Choose comma-listed parent passage rooms.
    +build/terrain <tags>          Request comma-listed terrain tags.
    +build/region <region>         Request a primary region, or 'none'.
    +build/inherit <field>         Clear a terrain or region request.
    +build/interior <name>         Add an interior to the current frontier street.
    +build/owner <character>       Assign this interior's proposed owner.
    +build/connect <room>=<direction>  Propose a public grid connection.
    +build/disconnect <direction>  Remove that proposed grid connection.
    +build/check                   Inspect the current proposal and warnings.
    +build/history                 Read its history.
    +build/submit [<token>]        Preview, then freeze the exact candidate.
    +build/withdraw [<token>] # <reason>  Withdraw the current submission.
    +build/discard [<token>]       Preview, then abandon the current draft.

    Stand in the project for edits. Room references use names or room #numbers.
    A room plan starts at the current coordinates; change a field before finishing.
    +collab, +property, +consent, +passage and +frontier handle their own tasks.
    Staff review and administration use +buildadmin.
    """

    key = "+build"
    switch_options = (
        "new",
        "enter",
        "room",
        "leave",
        "list",
        "name",
        "desc",
        "title",
        "purpose",
        "dig",
        "x",
        "y",
        "floor",
        "direction",
        "doorname",
        "back",
        "finish",
        "cancel",
        "door",
        "aliases",
        "attach",
        "entrance",
        "route",
        "terrain",
        "region",
        "inherit",
        "interior",
        "owner",
        "connect",
        "disconnect",
        "check",
        "history",
        "submit",
        "withdraw",
        "discard",
    )

    def run(self):
        """Dispatch one player action to the owning domain service."""
        actor, switch = self.caller, self.switch
        if switch in {"", "list"}:
            value = self.bare()
            if value:
                obj = support.project(actor, value)
                actor.msg(support.candidate_text(services.snapshot(obj)))
            else:
                actor.msg(
                    "\n".join(
                        f"{obj.pk}: {obj.name} — {obj.state}"
                        for obj in collaboration.visible_projects(actor)
                    )
                    or "No projects. Start with +build/new <name>."
                )
            return
        if switch == "new":
            obj = services.new_project(actor, self.bare())
            actor.msg(f"Project {obj.pk} created. Use +build/enter {obj.pk}.")
            return
        if switch == "enter":
            services.enter(actor, support.project(actor, self.bare()))
            return
        if switch == "leave":
            self.empty()
            services.leave(actor)
            return
        if switch == "cancel":
            self.empty()
            actor.attributes.remove(support.DRAFT_KEY)
            actor.msg("Room plan cancelled.")
            return
        obj, source = support.context(actor)
        if switch == "room":
            services.enter(actor, obj, room=support.draft_room(obj, self.bare()))
        elif switch in {"name", "desc", "title", "purpose"}:
            value = self.bare(prose=switch != "purpose")
            if switch == "purpose":
                value = value.lower()
            if switch in {"name", "desc"}:
                kwargs = {"name" if switch == "name" else "description": value}
                services.edit_project(
                    actor, obj, room=source, expected_version=obj.version, **kwargs
                )
            elif source.part_id:
                kwargs = {"name" if switch == "title" else "purpose": value}
                services.edit_part(actor, obj, source.part, expected_version=obj.version, **kwargs)
            else:
                kwargs = {"name" if switch == "title" else "purpose": value}
                services.edit_project(actor, obj, expected_version=obj.version, **kwargs)
        elif switch == "dig":
            if actor.attributes.has(support.DRAFT_KEY):
                raise ValidationError("Finish or cancel your existing room plan first.")
            if self.rhs is not None:
                dx, dy, dz, _ = frontier.direction(self.lhs)
                room = services.dig(
                    actor,
                    obj,
                    source,
                    self.rhs,
                    x=source.x + dx,
                    y=source.y + dy,
                    floor=source.floor + dz,
                    direction=self.lhs.casefold(),
                    expected_version=obj.version,
                )
                self.created_room(room)
            else:
                services._project(
                    obj, actor, editable=True, expected_version=obj.version, author=True
                )
                support.save_room_draft(
                    actor,
                    {
                        "project": obj.pk,
                        "version": obj.version,
                        "source": source.pk,
                        "name": services._text(self.bare()),
                        "x": source.x,
                        "y": source.y,
                        "floor": source.floor,
                        "door": None,
                        "back": None,
                        "direction": None,
                    },
                )
                actor.msg(
                    "Room plan started. Set /x, /y and /floor, or /direction, then +build/finish."
                )
        elif switch in {"x", "y", "floor", "direction", "doorname", "back", "finish"}:
            data, obj, source = support.room_draft(actor)
            if switch == "finish":
                self.empty()
                room = services.dig(
                    actor,
                    obj,
                    source,
                    data["name"],
                    x=data["x"],
                    y=data["y"],
                    floor=data["floor"],
                    door=data["door"],
                    back=data["back"],
                    direction=data["direction"],
                    expected_version=data["version"],
                )
                actor.attributes.remove(support.DRAFT_KEY)
                self.created_room(room)
            else:
                value = self.bare()
                if switch in {"x", "y", "floor"}:
                    if not value.removeprefix("-").isdecimal():
                        raise ValidationError(f"Use +build/{switch} <whole number>.")
                    data[switch] = int(value)
                elif switch == "direction":
                    dx, dy, dz, _ = frontier.direction(value)
                    data.update(
                        x=source.x + dx,
                        y=source.y + dy,
                        floor=source.floor + dz,
                        direction=value.casefold(),
                    )
                else:
                    data["door" if switch == "doorname" else "back"] = services._text(value, 100)
                support.save_room_draft(actor, data)
                actor.msg(f"Room plan {switch} set.")
            return
        elif switch == "door":
            target = support.draft_room(obj, self.lhs)
            door = services.add_door(
                actor, obj, source, target, self.rhs, expected_version=obj.version
            )
            actor.msg(f"Created door '{door.exit.key}'.")
        elif switch == "aliases":
            if self.rhs is None:
                raise ValidationError("Use +build/aliases <door>=<comma-listed aliases>.")
            rows = obj.doors.filter(source=source)
            door = (
                rows.get(object_id=support.number(self.lhs))
                if self.lhs.removeprefix("#").isdecimal()
                else support.select(rows, self.lhs, "exit__db_key")
            )
            services.set_door_aliases(
                actor, obj, door, self.rhslist if self.rhs else [], expected_version=obj.version
            )
        elif switch == "attach":
            if not self.rhs:
                raise ValidationError(
                    "Use +build/attach <room>=<entrance name or frontier direction>."
                )
            services.attach(
                actor,
                obj,
                support.world_room(actor, self.lhs),
                self.rhs,
                expected_version=obj.version,
            )
        elif switch == "entrance":
            services.set_entrance(
                actor, obj, self.bare(), part=source.part, expected_version=obj.version
            )
        elif switch == "route":
            route = [support.world_room(actor, value).pk for value in self.bare().split(",")]
            services.attach(
                actor,
                obj,
                obj.anchor,
                obj.entrance_name,
                passage=route,
                expected_version=obj.version,
            )
        elif switch in {"terrain", "region", "inherit"}:
            requested = dict(obj.requested_environment)
            value = self.bare()
            if switch == "inherit":
                value = value.lower()
            if switch == "terrain":
                requested["terrain"] = [item.strip() for item in value.split(",") if item.strip()]
            elif switch == "region":
                if not apps.is_installed("evennia_regions"):
                    raise ValidationError("Regions are not installed.")
                from evennia_regions.models import Region

                requested["region"] = (
                    None
                    if value.casefold() == "none"
                    else support.select(Region.objects.filter(is_archived=False), value).pk
                )
            else:
                if value not in {"terrain", "region"}:
                    raise ValidationError("Choose terrain or region.")
                requested.pop(value, None)
            services.request_environment(actor, obj, requested, expected_version=obj.version)
        elif switch == "interior":
            part = frontier.add_interior(
                actor,
                obj,
                source,
                self.bare(),
                owner=actor,
                entrance_name=self.lhs,
                expected_version=obj.version,
            )
            actor.msg(
                f"Interior {part.pk} created. Enter room #{part.entry_id} to set its owner and purpose."
            )
        elif switch == "owner":
            frontier.assign_owner(
                actor,
                obj,
                support.character(actor, self.bare()),
                part=source.part,
                expected_version=obj.version,
            )
        elif switch in {"connect", "disconnect"}:
            if switch == "connect" and not self.rhs:
                raise ValidationError("Use +build/connect <room>=<direction>.")
            label = self.rhs if switch == "connect" else self.bare()
            target = support.world_room(actor, self.lhs) if switch == "connect" else None
            frontier.propose_connection(
                actor,
                obj,
                source,
                target,
                label,
                remove=switch == "disconnect",
                expected_version=obj.version,
            )
        elif switch == "check":
            self.empty()
            actor.msg(support.candidate_text(services.snapshot(obj)))
        elif switch == "history":
            self.empty()
            actor.msg(
                "\n".join(
                    f"{row.created_at:%Y-%m-%d %H:%M}: {row.action} by {row.actor_name}: {row.data}"
                    for row in obj.audit.all()
                )
                or "No project history."
            )
        elif switch == "submit":
            token = self.bare()
            obj = services._project(obj, actor, editable=True)
            candidate = services.snapshot(obj)
            wording = collaboration.wording("contributor")
            state = {
                "candidate": candidate,
                "wording": wording,
                "wording_version": str(getattr(settings, "BUILDING_REUSE_VERSION", "1")),
            }
            if self.preview(
                "submit",
                state,
                token,
                "+build/submit ",
                support.candidate_text(candidate) + "\n" + wording,
            ):
                submission = services.submit(
                    actor, obj, expected_version=obj.version, acknowledgement=wording
                )
                actor.msg(f"Submission {submission.pk} frozen for review.")
        elif switch == "withdraw":
            value, reason = support.token_reason(self.bare())
            submission = obj.submissions.order_by("-revision").first()
            if obj.owner_id != actor.pk:
                raise PermissionDenied("Only the owner may withdraw the current submission.")
            if obj.state != "submitted" or not submission:
                raise ValidationError("This project has no submission to withdraw.")
            state = {
                "submission": submission.pk,
                "revision": submission.revision,
                "fingerprint": submission.fingerprint,
                "state": obj.state,
                "reason": reason,
            }
            generated = support.confirm(actor, "withdraw", state, value.strip())
            if generated:
                suffix = f" # {reason}" if reason else ""
                actor.msg(f"Withdraw {obj.name}? Confirm: +build/withdraw {generated}{suffix}")
            else:
                services.withdraw(
                    actor, submission, expected_revision=submission.revision, reason=reason
                )
                actor.msg("Submission withdrawn; the project is editable again.")
        elif switch == "discard":
            token = self.bare()
            obj = services._project(obj, actor, editable=True)
            state = {"project": obj.pk, "version": obj.version, "state": obj.state}
            if self.preview(
                "discard",
                state,
                token,
                "+build/discard ",
                "Discard this draft? Occupants and belongings return to safety.",
            ):
                services.discard(actor, obj, services.discard_token(actor, obj))
                actor.msg("Draft discarded.")
        else:
            raise ValidationError("Unknown player Building action. See help +build.")
        # These actions already report their own outcome.
        if switch not in {
            "dig",
            "door",
            "interior",
            "submit",
            "withdraw",
            "discard",
            "check",
            "history",
        }:
            actor.msg("Done.")

    def created_room(self, room):
        """Show the new door's actual triggers and optional Maps tag."""
        door = room.incoming.get(source_id=room.parent_id).exit
        label = ""
        if apps.is_installed("evennia_maps") and hasattr(door, "get_exit_tag"):
            tag = door.get_exit_tag()
            label = f", shown as <{tag}> {door.key}" if tag else ""
        triggers = ", ".join(dict.fromkeys([door.key, *door.aliases.all()]))
        self.caller.msg(
            f"Created room #{room.object_id}; door '{door.key}'{label}, triggered by {triggers}."
        )


class CmdCollab(BuildingCommand):
    """Collaborate on a project and agree to its exact candidate.

    +collab                        List your collaboration invitations.
    +collab/add <character>         Invite a collaborator to the current project.
    +collab/remove <character>      Remove a collaborator.
    +collab/accept <invitation>     Accept an invitation.
    +collab/decline <invitation>    Decline an invitation.
    +collab/leave <invitation>      Leave a collaboration.
    +collab/candidate [<project>]   Inspect the exact candidate.
    +collab/contributor <project>[=<token>]  Preview and acknowledge content reuse.
    +collab/ownership <project>[=<token>]    Preview and accept ownership boundaries.
    +collab/revoke <agreement>      Revoke your unconsumed acknowledgement.
    """

    key = "+collab"
    switch_options = (
        "list",
        "add",
        "remove",
        "accept",
        "decline",
        "leave",
        "candidate",
        "contributor",
        "ownership",
        "revoke",
    )

    def run(self):
        """Apply collaboration membership or a guarded candidate acknowledgement."""
        actor, switch = self.caller, self.switch
        if switch in {"", "list"}:
            self.empty()
            actor.msg(
                "\n".join(
                    f"{row.pk}: {row.project.name}; {row.state}"
                    for row in ProjectContributor.objects.filter(character=actor).select_related(
                        "project"
                    )
                )
                or "No collaboration invitations."
            )
        elif switch in {"add", "remove"}:
            obj, _ = support.context(actor)
            row = collaboration.invite(
                actor,
                obj,
                support.character(actor, self.bare()),
                expected_version=obj.version,
                remove=switch == "remove",
            )
            actor.msg(f"Collaboration invitation {row.pk}: {row.state}.")
        elif switch in {"accept", "decline", "leave"}:
            row = collaboration.answer(
                actor,
                ProjectContributor.objects.get(pk=support.number(self.bare())),
                accept=switch != "decline",
                leave=switch == "leave",
            )
            actor.msg(f"Collaboration {row.pk}: {row.state}.")
        elif switch == "candidate":
            obj = support.project(actor, self.bare())
            actor.msg(support.candidate_text(services.snapshot(obj)))
            actor.msg(
                "\n".join(
                    f"Agreement {row.pk}: {row.role}; {row.state}"
                    for row in obj.agreements.filter(actor=actor)
                )
                or "No acknowledgements from you."
            )
        elif switch in {"contributor", "ownership"}:
            obj = support.project(actor, self.lhs)
            if (actor.pk, switch) not in collaboration.required(obj):
                raise PermissionDenied("This candidate does not request that agreement from you.")
            candidate = services.snapshot(obj)
            wording = collaboration.wording(switch)
            state = {
                "candidate": candidate,
                "wording": wording,
                "wording_version": str(getattr(settings, "BUILDING_REUSE_VERSION", "1")),
            }
            if self.preview(
                f"collab-{switch}",
                state,
                self.rhs,
                f"+collab/{switch} {obj.pk}=",
                support.candidate_text(candidate) + "\n" + wording,
            ):
                row = collaboration.acknowledge(
                    actor,
                    obj,
                    role=switch,
                    expected_version=obj.version,
                    expected_fingerprint=services.fingerprint(candidate),
                    acknowledgement=wording,
                )
                actor.msg(f"Candidate agreement {row.pk} recorded ({switch}).")
        elif switch == "revoke":
            collaboration.revoke(
                actor, ProjectAgreement.objects.get(pk=support.number(self.bare()))
            )
            actor.msg("Candidate agreement revoked.")


class CmdProperty(BuildingCommand):
    """Manage a live property's rights from inside it.

    +property [<property>]         List or inspect visible properties.
    +property/name <text>          Rename the current room.
    +property/desc <text>          Describe the current room.
    +property/lock                 Lock the current property.
    +property/unlock               Unlock it.
    +property/resident <character> Add residence without installation rights.
    +property/installer <character> Add residence with installation rights.
    +property/unresident <character> Remove residence.
    +property/invite <character>   Invite with entry and map rights.
    +property/entry <character>    Invite with entry only.
    +property/maps <character>     Invite with maps only.
    +property/uninvite <character> Revoke an invitation.
    +property/invitations          List your pending invitations.
    +property/accept <invitation>  Accept one.
    +property/decline <invitation> Decline one.
    +property/override <characters> Restrict this room to comma-listed characters.
    +property/reset                Restore this room's normal access.

    An empty override allows only the owner. Entry never grants map access.
    """

    key = "+property"
    switch_options = (
        "name",
        "desc",
        "lock",
        "unlock",
        "resident",
        "installer",
        "unresident",
        "invite",
        "entry",
        "maps",
        "uninvite",
        "invitations",
        "accept",
        "decline",
        "override",
        "reset",
    )

    def run(self):
        """Delegate rights and live-room edits to owner-checked services."""
        actor, switch = self.caller, self.switch
        if switch == "":
            value = self.bare()
            rows = Property.objects.filter(state="live")
            visible = [
                obj.pk
                for obj in rows
                if any(
                    row.room and room_visibility(row.room, actor)
                    for row in obj.rooms.select_related("room")
                )
            ]
            rows = rows.filter(pk__in=visible)
            if value:
                rows = [support.select(rows, value)]
            lines = []
            for obj in rows:
                rooms = [
                    row.room
                    for row in obj.rooms.select_related("room")
                    if row.room and room_visibility(row.room, actor)
                ]
                lines.append(
                    f"{obj.pk}: {obj.name}; owner {obj.owner_name}; {'locked' if obj.locked else 'unlocked'}"
                )
                lines.append("Rooms: " + ", ".join(f"{room.dbref} {room.key}" for room in rooms))
                if obj.owner_id == actor.pk or is_staff(actor):
                    lines.extend(
                        f"Resident {row.character.key}: install={row.can_install}"
                        for row in obj.residents.select_related("character")
                    )
                    lines.extend(
                        f"Invitation {row.pk}: {row.character.key}; {row.state}; entry={row.entry}, maps={row.maps}"
                        for row in obj.invitations.select_related("character")
                    )
                    lines.extend(
                        f"{row.action} by {row.actor_name}: {row.data}"
                        for row in obj.audit.order_by("-pk")[:20]
                    )
            actor.msg("\n".join(lines) or "No properties available.")
            return
        if switch == "invitations":
            self.empty()
            actor.msg(
                "\n".join(
                    f"Invitation {row.pk}: {row.property.name}; entry={row.entry}, maps={row.maps}. Use +property/accept {row.pk} or +property/decline {row.pk}."
                    for row in GuestInvitation.objects.filter(
                        character=actor, state="pending"
                    ).select_related("property")
                )
                or "No pending invitations."
            )
            return
        if switch in {"accept", "decline"}:
            services.answer_invitation(
                actor,
                GuestInvitation.objects.get(pk=support.number(self.bare())),
                accept=switch == "accept",
            )
            actor.msg("Invitation answered.")
            return
        record = ownership(actor.location)
        if not record:
            raise ValidationError("Stand in the property you want to manage.")
        obj = record.property
        if switch in {"name", "desc"}:
            kwargs = {"name" if switch == "name" else "description": self.bare(prose=True)}
            services.edit_property_room(actor, actor.location, **kwargs)
        elif switch in {"lock", "unlock"}:
            self.empty()
            services.set_locked(actor, obj, switch == "lock")
        elif switch in {"resident", "installer", "unresident"}:
            services.set_resident(
                actor,
                obj,
                support.character(actor, self.bare()),
                remove=switch == "unresident",
                can_install=switch == "installer",
            )
        elif switch in {"invite", "entry", "maps", "uninvite"}:
            row = services.invite(
                actor,
                obj,
                support.character(actor, self.bare()),
                entry=switch != "maps",
                maps=switch != "entry",
                revoke=switch == "uninvite",
            )
            actor.msg(f"Invitation {row.pk}: {row.state}. The named character must accept.")
        elif switch == "override":
            value = self.bare()
            allowed = (
                [support.character(actor, item).pk for item in value.split(",")] if value else []
            )
            services.set_override(actor, actor.location, allowed)
        elif switch == "reset":
            self.empty()
            services.set_override(actor, actor.location, None)
        actor.msg("Done.")


class CmdConsent(BuildingCommand):
    """Request or answer apartment attachment consent.

    +consent [<request>]           List or inspect your requests.
    +consent/request               Request consent for the project where you stand.
    +consent/grant <request>[=<token>]  Preview, then grant exact-candidate consent.
    +consent/decline <request>      Decline a pending request.
    +consent/revoke <request>       Revoke granted consent before approval.
    """

    key = "+consent"
    switch_options = ("list", "show", "request", "grant", "decline", "revoke")

    def run(self):
        """Bind a consent token to its candidate, parent owner and current wording."""
        actor, switch = self.caller, self.switch
        if switch == "request":
            self.empty()
            obj, _ = support.context(actor)
            row = attachments.request_consent(actor, obj, expected_version=obj.version)
            actor.msg(
                f"Consent request {row.pk}: {row.state}. The parent owner can inspect +consent {row.pk}."
            )
            return
        rows = attachments.visible_consents(actor)
        if switch in {"", "list"} and not self.args:
            actor.msg(
                "\n".join(
                    f"{row.pk}: {row.project.name}; parent owner {row.owner_name}; {row.state}"
                    for row in rows
                )
                or "No consent requests."
            )
            return
        row = rows.get(pk=support.number(self.lhs))
        if switch in {"", "show"}:
            self.bare()
            actor.msg(
                f"Request {row.pk}: {row.state}\n{row.wording}\n{support.candidate_text(row.candidate)}"
            )
        elif switch == "grant":
            if row.owner_id != actor.pk or row.parent.owner_id != actor.pk:
                raise PermissionDenied("Only the current parent owner may grant consent.")
            state = {
                "request": row.pk,
                "candidate": services.snapshot(row.project),
                "requested_candidate": row.candidate,
                "state": row.state,
                "owner": row.parent.owner_id,
                "wording": row.wording,
                "wording_version": row.wording_version,
            }
            if self.preview(
                "consent-grant",
                state,
                self.rhs,
                f"+consent/grant {row.pk}=",
                row.wording + "\n" + support.candidate_text(row.candidate),
            ):
                attachments.answer_consent(actor, row, action="grant", acknowledgement=row.wording)
                actor.msg("Consent granted to this exact candidate and route.")
        elif switch in {"decline", "revoke"}:
            self.bare()
            attachments.answer_consent(actor, row, action=switch)
            actor.msg(f"Consent {switch} recorded.")


class CmdPassage(BuildingCommand):
    """Inspect and agree to staff-proposed replacement passage.

    +passage [<change>]            List pending changes or inspect one.
    +passage/accept <change>[=<token>]  Preview and accept the exact route.

    Both current owners must agree; only staff may propose and apply changes.
    """

    key = "+passage"
    switch_options = ("list", "show", "accept")

    def run(self):
        """Keep replacement-route inspection private to staff and affected owners."""
        actor, switch = self.caller, self.switch
        rows = PassageChange.objects.select_related("agreement__parent", "agreement__child")
        if not is_staff(actor):
            rows = rows.filter(Q(parent_owner=actor) | Q(child_owner=actor))
        if switch in {"", "list"} and not self.args:
            actor.msg(
                "\n".join(
                    f"{row.pk}: {row.reason}; parent accepted {row.parent_accepted}; apartment owner accepted {row.child_accepted}"
                    for row in rows.filter(state="pending")
                )
                or "No passage changes awaiting agreement."
            )
            return
        row = rows.get(pk=support.number(self.lhs))
        text = f"Passage change {row.pk}: rooms {row.route['rooms']}; {row.reason}\n{row.wording}\nParent accepted: {row.parent_accepted}; apartment owner accepted: {row.child_accepted}"
        if switch == "accept":
            attachments._current_change(row)
            state = {
                "change": row.pk,
                "route": row.route,
                "previous": row.previous_route,
                "parent_owner": row.parent_owner_id,
                "child_owner": row.child_owner_id,
                "wording": row.wording,
                "state": row.state,
                "reason": row.reason,
            }
            if self.preview("passage-accept", state, self.rhs, f"+passage/accept {row.pk}=", text):
                attachments.accept_passage(actor, row, acknowledgement=row.wording)
                actor.msg("Replacement passage accepted.")
        else:
            self.bare()
            actor.msg(text)


class CmdFrontier(BuildingCommand):
    """Propose public growth and maintain the room you steward.

    +frontier [<area>]             List or inspect public frontier areas.
    +frontier/new <name>           Start a frontier project; edit it with +build.
    +frontier/desc <text>          Maintain the current public room's description.
    +frontier/mood <text>          Set its mood.
    +frontier/relinquish [<token>] # <reason>  Preview, then give up stewardship.
    """

    key = "+frontier"
    switch_options = ("list", "show", "new", "desc", "mood", "relinquish")

    def run(self):
        """Separate public discovery and stewardship from draft authoring."""
        actor, switch = self.caller, self.switch
        if switch in {"", "list", "show"}:
            value = self.bare()
            rows = (
                Frontier.objects.all() if is_staff(actor) else Frontier.objects.filter(state="live")
            )
            if value:
                item = support.select(rows, value)
                actor.msg(
                    f"{item.pk}: {item.name}; {item.state}\n"
                    + "\n".join(
                        f"Room #{row.object_id}: {row.room.key if row.room else 'Missing'}; steward {row.steward_name or 'staff'}"
                        for row in item.rooms.select_related("room")
                    )
                )
            else:
                actor.msg(
                    "\n".join(f"{row.pk}: {row.name}; {row.state}" for row in rows)
                    or "No frontier areas."
                )
        elif switch == "new":
            obj = services.new_project(actor, self.bare(), kind="frontier")
            actor.msg(f"Frontier project {obj.pk} created. Use +build/enter {obj.pk}.")
        elif switch in {"desc", "mood"}:
            kwargs = {"description" if switch == "desc" else "mood": self.bare(prose=True)}
            frontier.edit_room(actor, actor.location, **kwargs)
            actor.msg("Frontier room updated.")
        elif switch == "relinquish":
            value, reason = support.token_reason(self.bare())
            record = FrontierRoom.objects.filter(
                room_id=actor.db_location_id, frontier__state="live"
            ).first()
            if not record or record.steward_id != actor.pk:
                raise PermissionDenied("Only this room's steward may relinquish it.")
            reason = services._text(reason, 10000)
            state = {
                "record": record.pk,
                "steward": record.steward_id,
                "assigned": record.assigned_at.isoformat(),
                "reason": reason,
            }
            token = support.confirm(actor, "relinquish", state, value.strip())
            if token:
                actor.msg(
                    f"Relinquish stewardship of {actor.location.key}? Confirm: +frontier/relinquish {token} # {reason}"
                )
            else:
                frontier.set_steward(
                    actor, record, expected_steward=record.steward_id, reason=reason
                )
                actor.msg("Stewardship relinquished.")
