# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Staff operations retained until the staff command update."""

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from evennia.commands.default.muxcommand import MuxCommand
from evennia.objects.models import ObjectDB

from . import attachments, collaboration, frontier, frontier_lifecycle, lifecycle, services
from .access import is_staff, require_revealed
from .models import (
    AttachmentAgreement,
    BuildProject,
    BuildSubmission,
    Frontier,
    FrontierRoom,
    PassageChange,
    Property,
)
from .policy import set_policy


class LegacyStaffBuild(MuxCommand):
    """Existing staff operations, called only for their explicit legacy forms.

    +build/environment/approve <submission> <revision>=<reason>
    +build/review <submission> <revision> <outcome>=<reason>
    +build/transfer <property> <expected owner> <new owner>=<reason>[;return|transfer]
    +build/policy <room>=<policy>
    +build/policy/region <region>=<policy>
    +build/archive[/children] <property>=<reason>
    +build/restore <property>=<reason>
    +build/quiet
    +build/passage/propose <agreement>=<room dbrefs>;<reason>
    +build/passage/apply <change>
    +build/geometry <submission> <revision>=<reason>
    +build/frontier/steward <room> <expected steward> <new steward>=<reason>
    +build/frontier/archive <frontier>=<reason>[;<frontiers>;<properties>]
    +build/frontier/restore <frontier>=<reason>
    """

    key = "+build"

    def func(self):
        actor = self.caller
        try:
            require_revealed(actor)
            if not is_staff(actor):
                raise PermissionDenied("Only Building staff may use that action.")
            switches = set(self.switches)
            parts = self.lhs.split()

            def number(index=0):
                return int(parts[index].removeprefix("#"))

            def project():
                obj = BuildProject.objects.get(pk=number())
                if not collaboration.can_inspect(actor, obj):
                    raise PermissionDenied("This project is private.")
                return obj

            def character(index):
                obj = ObjectDB.objects.get(pk=number(index))
                if not obj.is_typeclass("evennia.objects.objects.DefaultCharacter", exact=False):
                    raise ValidationError("Choose a character.")
                return obj

            if "geometry" in switches:
                frontier.approve_geometry(
                    actor,
                    BuildSubmission.objects.get(pk=number()),
                    expected_revision=number(1),
                    reason=self.rhs or "",
                )
                actor.msg("Manual geometry review recorded for this exact submission.")
            elif "frontier" in switches:
                if "steward" in switches:
                    frontier.set_steward(
                        actor,
                        FrontierRoom.objects.get(object_id=number()),
                        character(2) if number(2) else None,
                        expected_steward=number(1) or None,
                        reason=self.rhs or "",
                    )
                elif "archive" in switches:
                    values = (self.rhs or "").split(";")
                    frontier_lifecycle.archive(
                        actor,
                        Frontier.objects.get(pk=number()),
                        reason=values[0],
                        affected_frontiers=[
                            Frontier.objects.get(pk=int(pk.strip()))
                            for pk in values[1].split(",")
                            if pk.strip()
                        ]
                        if len(values) > 1
                        else [],
                        affected_properties=[
                            Property.objects.get(pk=int(pk.strip()))
                            for pk in values[2].split(",")
                            if pk.strip()
                        ]
                        if len(values) > 2
                        else [],
                    )
                elif "restore" in switches:
                    frontier_lifecycle.restore(
                        actor, Frontier.objects.get(pk=number()), reason=self.rhs or ""
                    )
            elif "passage" in switches:
                if "propose" in switches:
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
                    attachments.apply_passage(actor, change)
            elif switches & {"archive", "restore"}:
                obj = Property.objects.get(pk=number())
                if "archive" in switches:
                    lifecycle.archive(
                        actor, obj, reason=self.rhs or "", include_children="children" in switches
                    )
                else:
                    lifecycle.restore(actor, obj, reason=self.rhs or "")
            elif "quiet" in switches:
                lifecycle.quiet_list(actor)
                lifecycle.check_quiet()
                frontier_lifecycle.check_quiet()
                actor.msg(
                    "\n".join(
                        f"{row.property_id}: {row.property.name}; owner {row.property.owner_name}; {row.reason}; last played {row.last_played or 'unknown'}"
                        for row in lifecycle.quiet_list(actor)
                    )
                    or "No properties need quiet review."
                )
                actor.msg(
                    "\n".join(
                        f"Frontier room #{row.room.object_id}: {row.room.frontier.name}; steward {row.room.steward_name}; last played {row.last_played or 'unknown'}. Review only; no rights changed."
                        for row in frontier_lifecycle.quiet_list(actor)
                    )
                    or "No stewards need quiet review."
                )
            elif "environment" in switches:
                services.approve_environment(
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
            elif "transfer" in switches:
                reason, _, stock = (self.rhs or "").rpartition(";")
                if stock.strip() not in {"return", "transfer"}:
                    reason, stock = (self.rhs or "", None)
                services.transfer(
                    actor,
                    Property.objects.get(pk=number()),
                    character(2),
                    expected_owner=number(1),
                    reason=reason,
                    stock_disposition=stock.strip() if stock else None,
                )
            elif "policy" in switches:
                target = number() if "region" in switches else ObjectDB.objects.get(pk=number())
                set_policy(actor, target, (self.rhs or "").strip(), region="region" in switches)
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
