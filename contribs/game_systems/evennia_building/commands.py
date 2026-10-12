"""Command adapter; all authorization and mutation belong to services."""

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from evennia.commands.default.muxcommand import MuxCommand
from evennia.objects.models import ObjectDB

from . import attachments, lifecycle, services
from .access import is_staff, require_revealed
from .models import (
    AttachmentAgreement,
    BuildProject,
    BuildSubmission,
    GuestInvitation,
    PassageChange,
    Property,
)
from .policy import set_policy
from .visibility import room_visibility


class CmdBuild(MuxCommand):
    """Create and manage a reviewed interior.

    +build/new interior=<name>
    +build/list | +build/enter <project> | +build/leave
    +build/dig <project> <source room> <floor> <x> <y>=<name>,<door>,<back>
    +build/door <project> <source room> <target room>=<door>
    +build/name|desc <project> <room>=<text>
    +build/property/name|desc <room dbref>=<text>
    +build/environment <project>=<JSON terrain list and/or region>
    +build/environment/approve <submission> <revision>=<reason> (staff)
    +build/name|purpose <project>=<value>
    +build/attach <project> <anchor dbref>=<entrance name>
    +build/check|history <project>
    +build/submit <project> <version>=<displayed acknowledgement>
    +build/withdraw <submission> <revision>=<reason>
    +build/review <submission> <revision> <outcome>=<reason> (staff)
    +build/property [property]
    +build/resident/add|remove|install <property> <character dbref>
    +build/invite (list pending invitations)
    +build/invite[/entry|maps]|uninvite <property> <character dbref>
    +build/invite/accept|decline <invitation>
    +build/lock|unlock <property>
    +build/override <room dbref>=<character dbrefs, or empty for owner only>
    +build/override/reset <room dbref>
    +build/discard <project>[=<confirmation token>]
    +build/transfer <property> <expected owner> <new owner>=<reason> (staff)
    +build/policy <room dbref>=open|residential|commercial|closed|reset (staff)
    +build/policy/region <region>=open|residential|commercial|closed|reset (staff)
    +build/attach <project> <anchor dbref>=<entrance name>[;<passage room dbrefs>]
    +build/consent/request <project> | +build/consent/list
    +build/consent/show|grant|decline|revoke <request>[=<displayed agreement wording>]
    +build/archive[/children] <property>=<reason> (staff)
    +build/restore <property>=<reason> (staff; parent before apartment)
    +build/quiet (staff review flags; never automatic reclamation)
    +build/passage/propose <agreement>=<room dbrefs>;<reason> (staff)
    +build/passage/show|accept|apply <change>[=<displayed agreement wording>]
    """

    key = "+build"
    locks = "cmd:all()"
    help_category = "Building"

    def func(self):
        actor = self.caller
        try:
            require_revealed(actor)
            switches = set(self.switches)
            parts = self.lhs.split()

            def number(index=0):
                return int(parts[index].removeprefix("#"))

            def project():
                obj = BuildProject.objects.get(pk=number())
                if obj.owner_id != actor.pk and not is_staff(actor):
                    raise PermissionDenied("This project is private.")
                return obj

            def character(index):
                obj = ObjectDB.objects.get(pk=number(index))
                if not obj.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False):
                    raise ValidationError("Choose a character.")
                return obj

            if "consent" in switches:
                if "request" in switches:
                    obj = project()
                    consent = attachments.request_consent(actor, obj, expected_version=obj.version)
                    actor.msg(
                        f"Consent request {consent.pk}: {consent.state}. The parent owner must inspect +build/consent/show {consent.pk}."
                    )
                elif "list" in switches:
                    actor.msg(
                        "\n".join(
                            f"{row.pk}: {row.project.name}; parent owner {row.owner_name}; {row.state}"
                            for row in attachments.visible_consents(actor)
                        )
                        or "No consent requests."
                    )
                else:
                    consent = attachments.visible_consents(actor).get(pk=number())
                    if "show" in switches:
                        import json

                        actor.msg(
                            f"Request {consent.pk}: {consent.state}\n{consent.wording}\n{json.dumps(consent.candidate, indent=2)}"
                        )
                    else:
                        action = next(
                            (key for key in ("grant", "decline", "revoke") if key in switches), ""
                        )
                        attachments.answer_consent(
                            actor, consent, action=action, acknowledgement=self.rhs or ""
                        )
            elif "passage" in switches:
                if "list" in switches:
                    rows = PassageChange.objects.filter(state="pending")
                    if not is_staff(actor):
                        from django.db.models import Q

                        rows = rows.filter(Q(parent_owner=actor) | Q(child_owner=actor))
                    actor.msg(
                        "\n".join(
                            f"{row.pk}: {row.reason}; parent accepted {row.parent_accepted}; apartment owner accepted {row.child_accepted}"
                            for row in rows
                        )
                        or "No passage changes awaiting agreement."
                    )
                elif "propose" in switches:
                    route, reason = (self.rhs or "").split(";", 1)
                    change = attachments.propose_passage(
                        actor,
                        AttachmentAgreement.objects.get(pk=number()),
                        [int(pk.strip().removeprefix("#")) for pk in route.split(",")],
                        reason=reason,
                    )
                    actor.msg(
                        f"Passage change {change.pk}: both affected owners must inspect and accept it before staff applies it."
                    )
                else:
                    change = PassageChange.objects.select_related("agreement").get(pk=number())
                    if not is_staff(actor) and actor.pk not in {
                        change.parent_owner_id,
                        change.child_owner_id,
                    }:
                        raise PermissionDenied("This passage proposal is private.")
                    if "show" in switches:
                        actor.msg(
                            f"Passage change {change.pk}: {change.route}; {change.reason}\n{change.wording}\nParent accepted: {change.parent_accepted}; apartment owner accepted: {change.child_accepted}"
                        )
                    elif "accept" in switches:
                        attachments.accept_passage(actor, change, acknowledgement=self.rhs or "")
                    elif "apply" in switches:
                        attachments.apply_passage(actor, change)
                    else:
                        raise ValidationError("Choose passage propose, show, accept or apply.")
            elif switches & {"archive", "restore"}:
                obj = Property.objects.get(pk=number())
                if "archive" in switches:
                    lifecycle.archive(
                        actor, obj, reason=self.rhs or "", include_children="children" in switches
                    )
                else:
                    lifecycle.restore(actor, obj, reason=self.rhs or "")
            elif "quiet" in switches:
                lifecycle.quiet_list(actor)  # Authorize before the maintenance write.
                lifecycle.check_quiet()
                actor.msg(
                    "\n".join(
                        f"{row.property_id}: {row.property.name}; owner {row.property.owner_name}; {row.reason}; last played {row.last_played or 'unknown'}"
                        for row in lifecycle.quiet_list(actor)
                    )
                    or "No properties need quiet review."
                )
            elif "new" in switches:
                obj = services.new_project(actor, self.rhs or "", kind=self.lhs.strip())
                actor.msg(
                    f"Project {obj.pk}, version {obj.version}, created. Use +build/enter {obj.pk}."
                )
            elif "leave" in switches:
                services.leave(actor)
            elif "enter" in switches:
                services.enter(actor, project())
            elif "list" in switches or not switches:
                rows = (
                    BuildProject.objects.all()
                    if is_staff(actor)
                    else BuildProject.objects.filter(owner=actor)
                )
                actor.msg(
                    "\n".join(
                        f"{obj.pk}: {obj.name} — {obj.state}, version {obj.version}" for obj in rows
                    )
                    or "No projects. Start with +build/new interior=<name>."
                )
            elif "dig" in switches:
                obj = project()
                values = (self.rhs or "").split(",")
                room = services.dig(
                    actor,
                    obj,
                    obj.rooms.get(pk=number(1)),
                    values[0],
                    door=values[1] if len(values) > 1 else "inside",
                    back=values[2] if len(values) > 2 else "out",
                    floor=number(2),
                    x=number(3),
                    y=number(4),
                    expected_version=obj.version,
                )
                actor.msg(f"Draft room {room.pk} created.")
            elif "door" in switches:
                obj = project()
                services.add_door(
                    actor,
                    obj,
                    obj.rooms.get(pk=number(1)),
                    obj.rooms.get(pk=number(2)),
                    self.rhs or "",
                    expected_version=obj.version,
                )
            elif "environment" in switches:
                if "approve" in switches:
                    services.approve_environment(
                        actor,
                        BuildSubmission.objects.get(pk=number()),
                        expected_revision=number(1),
                        reason=self.rhs or "",
                    )
                else:
                    import json

                    obj = project()
                    services.request_environment(
                        actor, obj, json.loads(self.rhs or "{}"), expected_version=obj.version
                    )
            elif "property" in switches and switches & {"name", "desc"}:
                services.edit_property_room(
                    actor,
                    ObjectDB.objects.get(pk=number()),
                    **{"description" if "desc" in switches else "name": self.rhs or ""},
                )
            elif switches & {"name", "desc", "purpose"}:
                obj = project()
                kwargs = {"room": obj.rooms.get(pk=number(1))} if len(parts) > 1 else {}
                field = (
                    "description"
                    if "desc" in switches
                    else "purpose"
                    if "purpose" in switches
                    else "name"
                )
                services.edit_project(
                    actor, obj, expected_version=obj.version, **kwargs, **{field: self.rhs or ""}
                )
            elif "attach" in switches:
                obj = project()
                values = (self.rhs or "").split(";", 1)
                services.attach(
                    actor,
                    obj,
                    ObjectDB.objects.get(pk=number(1)),
                    values[0],
                    expected_version=obj.version,
                    passage=[int(pk.strip().removeprefix("#")) for pk in values[1].split(",")]
                    if len(values) > 1
                    else None,
                )
            elif "check" in switches:
                obj = project()
                report = services.check_project(obj)
                actor.msg(
                    f"Project {obj.pk}, version {obj.version}: {report}\nAcknowledgement: {getattr(settings, 'BUILDING_REUSE_ACKNOWLEDGEMENT', 'I acknowledge that this submitted content may be reused by this game.')}\nRooms: "
                    + ", ".join(
                        f"{room.pk}: {room.room.key}"
                        for room in obj.rooms.select_related("room")
                        if room.room
                    )
                )
            elif "submit" in switches:
                obj = services.submit(
                    actor, project(), expected_version=number(1), acknowledgement=self.rhs or ""
                )
                actor.msg(f"Submission {obj.pk}, revision {obj.revision}, frozen for review.")
            elif "withdraw" in switches:
                services.withdraw(
                    actor,
                    BuildSubmission.objects.get(pk=number()),
                    expected_revision=number(1),
                    reason=self.rhs or "",
                )
            elif "review" in switches:
                if not parts:
                    if not is_staff(actor):
                        raise PermissionDenied
                    actor.msg(
                        "\n".join(
                            f"{obj.pk}: {obj.project.name}, revision {obj.revision}"
                            for obj in BuildSubmission.objects.filter(
                                project__state="submitted", review__isnull=True
                            )
                        )
                    )
                    return
                services.review(
                    actor,
                    BuildSubmission.objects.get(pk=number()),
                    expected_revision=number(1),
                    outcome=parts[2],
                    reason=self.rhs or "",
                )
            elif "history" in switches:
                obj = project()
                actor.msg(
                    "\n".join(
                        f"{row.created_at:%Y-%m-%d %H:%M}: {row.action} by {row.actor_name}: {row.data}"
                        for row in obj.audit.all()
                    )
                )
            elif "discard" in switches:
                obj = project()
                if self.rhs:
                    services.discard(actor, obj, self.rhs.strip())
                else:
                    actor.msg(
                        f"This removes draft geometry and safely returns occupants/belongings. Confirm with +build/discard {obj.pk}={services.discard_token(actor, obj)}"
                    )
                    return
            elif "property" in switches:
                rows = (
                    Property.objects.filter(pk=number())
                    if parts
                    else Property.objects.filter(state="live")
                )
                lines = []
                for obj in rows:
                    rooms = [
                        record.room
                        for record in obj.rooms.select_related("room")
                        if record.room and room_visibility(record.room, actor)
                    ]
                    if rooms:
                        lines.append(
                            f"{obj.pk}: {obj.name}; owner {obj.owner_name}; {'locked' if obj.locked else 'unlocked'}"
                        )
                        lines.append(
                            "Rooms: " + ", ".join(f"{room.dbref} {room.key}" for room in rooms)
                        )
                        if obj.owner_id == actor.pk or is_staff(actor):
                            lines += [
                                f"Resident {row.character_id}: {row.character.key}; install={row.can_install}"
                                for row in obj.residents.select_related("character")
                            ]
                            lines += [
                                f"Invitation {row.pk} to {row.character_id} ({row.character.key}): {row.state}; entry={row.entry}, maps={row.maps}"
                                for row in obj.invitations.select_related("character")
                            ]
                            lines += [
                                f"{row.action} by {row.actor_name}: {row.data}"
                                for row in obj.audit.order_by("-pk")[:20]
                            ]
                actor.msg("\n".join(lines) or "No properties available.")
            elif "resident" in switches:
                obj = Property.objects.get(pk=number())
                services.set_resident(
                    actor,
                    obj,
                    character(1),
                    remove="remove" in switches,
                    can_install="install" in switches,
                )
            elif "invite" in switches and not parts:
                actor.msg(
                    "\n".join(
                        f"Invitation {row.pk}: {row.property.name}; entry={row.entry}, maps={row.maps}. Use +build/invite/accept {row.pk} or /decline {row.pk}."
                        for row in GuestInvitation.objects.filter(
                            character=actor, state="pending"
                        ).select_related("property")
                    )
                    or "No pending invitations."
                )
            elif "invite" in switches and switches & {"accept", "decline"}:
                services.answer_invitation(
                    actor, GuestInvitation.objects.get(pk=number()), accept="accept" in switches
                )
            elif switches & {"invite", "uninvite"}:
                invitation = services.invite(
                    actor,
                    Property.objects.get(pk=number()),
                    character(1),
                    revoke="uninvite" in switches,
                    entry="entry" in switches or not switches & {"entry", "maps"},
                    maps="maps" in switches or not switches & {"entry", "maps"},
                )
                actor.msg(
                    f"Invitation {invitation.pk}: {invitation.state}. The invited character must explicitly accept."
                )
            elif switches & {"lock", "unlock"}:
                services.set_locked(actor, Property.objects.get(pk=number()), "lock" in switches)
            elif "override" in switches:
                allowed = (
                    None
                    if "reset" in switches
                    else [
                        int(value.strip().removeprefix("#"))
                        for value in (self.rhs or "").split(",")
                        if value.strip()
                    ]
                )
                services.set_override(actor, ObjectDB.objects.get(pk=number()), allowed)
            elif "transfer" in switches:
                services.transfer(
                    actor,
                    Property.objects.get(pk=number()),
                    character(2),
                    expected_owner=number(1),
                    reason=self.rhs or "",
                )
            elif "policy" in switches:
                target = number() if "region" in switches else ObjectDB.objects.get(pk=number())
                set_policy(actor, target, (self.rhs or "").strip(), region="region" in switches)
            else:
                raise ValidationError("Unknown Building action. See help +build.")
            actor.msg("Done.")
        except (
            ValidationError,
            PermissionDenied,
            ObjectDoesNotExist,
            ValueError,
            IndexError,
        ) as exc:
            actor.msg(
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else str(exc) or "Check the action and identifiers; see help +build."
            )
