# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Staff command adapter: private drafts, complete previews and guarded domain calls."""

from uuid import uuid4

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Subquery
from evennia.objects.models import ObjectDB
from evennia.utils.dbserialize import deserialize

from . import attachments, frontier, frontier_lifecycle, lifecycle, services
from . import command_support as support
from . import staff_state as state
from .models import (
    AttachmentAgreement,
    BuildSubmission,
    Frontier,
    FrontierRoom,
    PassageChange,
    Property,
)
from .policy import set_policy

DRAFT_KEY = "building_staff_draft"
STARTS = {"transfer", "archive", "retire", "steward", "passage"}
FIELDS = {
    "transfer": {"stock", "grants", "reason"},
    "archive": {"children", "reason"},
    "retire": {"frontiers", "properties", "replacement", "unreplace", "reason"},
    "steward": {"reason"},
    "passage": {"reason"},
}


def arguments(command):
    """Separate one target/value relation and an optional literal trailing reason."""
    text, _, reason = command.args.partition(" # ")
    target, equals, value = text.partition("=")
    return target.strip(), value.strip() if equals else None, reason.strip()


def reason_text(reason):
    """Give a useful prompt for the required audited reason."""
    if not reason:
        raise ValidationError("Add a reason after ' # ', or set +buildadmin/reason on your draft.")
    return services._text(reason, 10000)


def _draft(actor):
    data = actor.attributes.get(DRAFT_KEY)
    if not data:
        raise ValidationError(
            "Start a transfer, archive, retirement, stewardship or passage draft first."
        )
    return deserialize(data)


def _save(actor, data):
    data["revision"] += 1
    actor.attributes.add(DRAFT_KEY, data)


def _property(value):
    return support.select(Property.objects.all(), value)


def _frontier(value):
    return support.select(Frontier.objects.all(), value)


def _port(actor, value):
    if value.count("/") != 1:
        raise ValidationError("Use one room/direction address, such as #12/north.")
    room, label = value.rsplit("/", 1)
    label = label.strip().casefold()
    frontier.direction(label)
    return support.world_room(actor, room), label


def _start(command):
    actor, kind = command.caller, command.switch
    if actor.attributes.has(DRAFT_KEY):
        raise ValidationError("Finish or cancel your existing staff draft first.")
    target, value, reason = arguments(command)
    plan = {"kind": kind, "nonce": uuid4().hex, "revision": 1, "reason": reason}
    if reason:
        reason_text(reason)
    if kind == "transfer":
        if not value:
            raise ValidationError("Use +buildadmin/transfer <property>=<character> # <reason>.")
        property = _property(target)
        if property.state not in {"live", "archived"}:
            raise ValidationError("Choose a live or archived property.")
        recipient = support.character(actor, value)
        plan.update(
            target=property.pk,
            expected_owner=property.owner_id,
            recipient=recipient.pk,
            stock=None,
            retain_grants=False,
        )
    elif kind == "archive":
        if value is not None:
            raise ValidationError("Use +buildadmin/archive <property> # <reason>.")
        property = _property(target)
        if property.state != "live":
            raise ValidationError("Choose a live property to archive.")
        plan.update(target=property.pk, expected_owner=property.owner_id, children=False)
    elif kind == "retire":
        if value is not None:
            raise ValidationError("Use +buildadmin/retire <frontier> # <reason>.")
        item = _frontier(target)
        if item.state != "live":
            raise ValidationError("Choose a live frontier area to retire.")
        plan.update(target=item.pk, frontiers=[], properties=[], replacements=[])
    elif kind == "steward":
        if not value:
            raise ValidationError("Use +buildadmin/steward <room>=<character or none> # <reason>.")
        room = support.world_room(actor, target)
        record = FrontierRoom.objects.filter(room=room, frontier__state="live").first()
        if not record:
            raise ValidationError("Choose a room in a live frontier area.")
        recipient = None if value.casefold() == "none" else support.character(actor, value).pk
        plan.update(
            target=record.pk,
            expected_steward=record.steward_id,
            assigned=record.assigned_at.isoformat(),
            recipient=recipient,
        )
    elif kind == "passage":
        if not value:
            raise ValidationError(
                "Use +buildadmin/passage <agreement>=<comma-listed rooms> # <reason>."
            )
        agreement = AttachmentAgreement.objects.get(pk=support.number(target))
        route = [support.world_room(actor, text).pk for text in value.split(",")]
        attachments.route_snapshot(agreement.parent, route, agreement.child.anchor_id)
        plan.update(target=agreement.pk, route=route)
    actor.attributes.add(DRAFT_KEY, plan)
    actor.msg(f"{kind.title()} draft started. Set any remaining fields, then +buildadmin/finish.")


def _field(command):
    actor, field = command.caller, command.switch
    plan = _draft(actor)
    if field not in FIELDS[plan["kind"]]:
        raise ValidationError(f"That field is not part of your {plan['kind']} draft.")
    if field == "reason":
        plan["reason"] = reason_text(command.bare(prose=True))
    elif field == "stock":
        value = command.bare().casefold()
        if value not in {"return", "transfer"}:
            raise ValidationError("Choose return or transfer for shop stock.")
        plan["stock"] = value
    elif field == "grants":
        value = command.bare().casefold()
        if value not in {"clear", "retain"}:
            raise ValidationError("Choose clear or retain for access grants.")
        plan["retain_grants"] = value == "retain"
    elif field == "children":
        value = command.bare().casefold()
        if value not in {"yes", "no"}:
            raise ValidationError("Choose yes or no for affected apartments.")
        plan["children"] = value == "yes"
    elif field in {"frontiers", "properties"}:
        value = command.bare()
        query = (
            Frontier.objects.filter(state="live")
            if field == "frontiers"
            else Property.objects.filter(state="live")
        )
        plan[field] = (
            sorted({support.select(query, text).pk for text in value.split(",")}) if value else []
        )
    elif field in {"replacement", "unreplace"}:
        target, value, reason = arguments(command)
        if reason:
            raise ValidationError("Set the overall plan reason with +buildadmin/reason.")
        source, label = _port(actor, target)
        port = (source.pk, tuple(frontier.direction(label)))
        replacements = [
            dict(row)
            for row in plan["replacements"]
            if (row["source"], tuple(frontier.direction(row["direction"]))) != port
        ]
        if field == "replacement":
            if not value:
                raise ValidationError("Use +buildadmin/replacement <room>/<direction>=<room>.")
            destination = support.world_room(actor, value)
            frontier.public_room(source)
            frontier.public_room(destination)
            replacements.append({"source": source.pk, "target": destination.pk, "direction": label})
        elif value is not None or len(replacements) == len(plan["replacements"]):
            raise ValidationError("Choose an existing replacement room/direction address.")
        plan["replacements"] = sorted(
            replacements, key=lambda row: (row["source"], row["direction"])
        )
    _save(actor, plan)
    actor.msg(f"Staff draft {field} set.")


def _plan_state(plan):
    """Build the complete current effect set before signing or applying a draft."""
    kind = plan["kind"]
    if kind in {"transfer", "archive"}:
        property = Property.objects.get(pk=plan["target"])
        if property.owner_id != plan["expected_owner"]:
            raise ValidationError("The property owner changed. Cancel and start a fresh draft.")
        if kind == "transfer":
            recipient = services._character(ObjectDB.objects.get(pk=plan["recipient"]))
            data = state.property_state(property)
            if data.get("shops") and not plan["stock"]:
                raise ValidationError(
                    "This property has a shop. Explicitly set +buildadmin/stock return or transfer."
                )
            return {"property": data, "recipient": {"id": recipient.pk, "name": recipient.key}}
        group = state.archive_group(property, include_children=plan["children"])
        return {"properties": [state.property_state(row, occupants=True) for row in group]}
    if kind == "retire":
        return state.retirement_state(plan)
    if kind == "steward":
        record = FrontierRoom.objects.select_related("room", "frontier").get(pk=plan["target"])
        if (
            record.steward_id != plan["expected_steward"]
            or record.assigned_at.isoformat() != plan["assigned"]
        ):
            raise ValidationError("The steward changed. Cancel and start a fresh draft.")
        if record.frontier.state != "live":
            raise ValidationError("Choose a live frontier room.")
        recipient = (
            services._character(ObjectDB.objects.get(pk=plan["recipient"]))
            if plan["recipient"]
            else None
        )
        return {
            "room": state.room_state(record.room),
            "frontier": record.frontier_id,
            "steward": record.steward_id,
            "assigned": record.assigned_at.isoformat(),
            "recipient": None if not recipient else {"id": recipient.pk, "name": recipient.key},
        }
    agreement = AttachmentAgreement.objects.select_related("parent", "child").get(pk=plan["target"])
    return {
        "agreement": agreement.pk,
        "parent": state.property_state(agreement.parent),
        "child": state.property_state(agreement.child),
        "previous": agreement.route,
        "route": attachments.route_snapshot(
            agreement.parent, plan["route"], agreement.child.anchor_id
        ),
        "wording": attachments.WORDING,
        "wording_version": attachments.WORDING_VERSION,
    }


def _count(items, noun):
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"


def _summary(plan, current):
    """Explain choices and affected owners without printing internal guard fields."""
    lines = [f"{plan['kind'].title()} plan. Reason: {plan['reason'] or 'not yet set'}"]
    properties = current.get("properties", []) + (
        [current["property"]] if "property" in current else []
    )
    for property in properties:
        owner = (
            ObjectDB.objects.filter(pk=property["owner_id"])
            .values_list("db_key", flat=True)
            .first()
        )
        lines.append(
            f"Property {property['id']}: {property['name']}; owner {owner or 'missing'} (#{property['owner_id']}); {property['state']}; {_count(property['rooms'], 'room')}."
        )
    if plan["kind"] == "transfer":
        lines.append(
            f"New owner: {current['recipient']['name']} (#{plan['recipient']}). Grants: {'retain' if plan['retain_grants'] else 'clear'}. Stock: {plan['stock'] or 'no shop stock choice'}."
        )
        for listing in current["property"].get("stock", []):
            if listing["status"] == "active":
                lines.append(
                    f"Shop listing {listing['id']}: {listing['assets']}; price {listing['price']}."
                )
    if plan["kind"] == "archive":
        lines.append(
            f"Include active apartments: {'yes' if plan['children'] else 'no'}. Occupants return to safety; belongings and room identities remain."
        )
    if plan["kind"] == "retire":
        for item in current["frontiers"]:
            lines.append(
                f"Frontier {item['id']}: {item['name']}; {_count(item['rooms'], 'public room')}."
            )
        for row in plan["replacements"]:
            lines.append(
                f"Replacement: room #{row['source']}/{row['direction']} to room #{row['target']}, in both directions."
            )
        lines.append(
            "The listed public rooms and homes are the complete affected group. Occupants return to safety."
        )
    if plan["kind"] == "steward":
        name = (
            current["recipient"]["name"]
            if current["recipient"]
            else "staff (no individual steward)"
        )
        lines.append(
            f"Room #{current['room']['id']}: {current['room']['db_key']}; current steward #{current['steward']}; new steward {name}."
        )
    if plan["kind"] == "passage":
        lines.append(
            f"Parent property {current['parent']['id']}, owner #{current['parent']['owner_id']}; apartment {current['child']['id']}, owner #{current['child']['owner_id']}."
        )
        lines.append("Replacement route: " + ", ".join(f"#{pk}" for pk in plan["route"]))
        lines.append(current["wording"])
        lines.append(
            "This only proposes passage. Both current owners must separately accept before staff can apply it."
        )
    return "\n".join(lines)


def _finish(command):
    actor = command.caller
    plan = _draft(actor)
    token = command.bare()
    reason_text(plan["reason"])
    current = _plan_state(plan)
    if not command.preview(
        "staff-finish",
        {"plan": plan, "current": current},
        token,
        "+buildadmin/finish ",
        _summary(plan, current),
    ):
        return
    kind, target = plan["kind"], plan["target"]
    if kind == "transfer":
        services.transfer(
            actor,
            Property.objects.get(pk=target),
            ObjectDB.objects.get(pk=plan["recipient"]),
            expected_owner=plan["expected_owner"],
            reason=plan["reason"],
            retain_grants=plan["retain_grants"],
            stock_disposition=plan["stock"],
        )
    elif kind == "archive":
        lifecycle.archive(
            actor,
            Property.objects.get(pk=target),
            reason=plan["reason"],
            include_children=plan["children"],
        )
    elif kind == "retire":
        frontier_lifecycle.archive(
            actor,
            Frontier.objects.get(pk=target),
            reason=plan["reason"],
            affected_frontiers=list(Frontier.objects.filter(pk__in=plan["frontiers"])),
            affected_properties=list(Property.objects.filter(pk__in=plan["properties"])),
            replacements=plan["replacements"],
        )
    elif kind == "steward":
        frontier.set_steward(
            actor,
            FrontierRoom.objects.get(pk=target),
            ObjectDB.objects.get(pk=plan["recipient"]) if plan["recipient"] else None,
            expected_steward=plan["expected_steward"],
            reason=plan["reason"],
        )
    else:
        change = attachments.propose_passage(
            actor, AttachmentAgreement.objects.get(pk=target), plan["route"], reason=plan["reason"]
        )
    actor.attributes.remove(DRAFT_KEY)
    if kind == "passage":
        actor.msg(
            f"Passage change {change.pk} proposed. Both owners can inspect +passage {change.pk}."
        )
    else:
        actor.msg(f"{kind.title()} plan applied.")


def _review(command):
    target, token, reason = arguments(command)
    reason = reason_text(reason)
    submission = BuildSubmission.objects.get(pk=support.number(target))
    project, submission, current = state.submission_state(submission)
    action = command.switch
    if action == "approve":
        current["current_candidate"] = services.snapshot(project)
    text = (
        f"{action.title()} submission {submission.pk}: {project.name}.\nReason: {reason}\n"
        + support.candidate_text(submission.snapshot)
    )
    if action == "environment":
        requested = services._environment(submission.snapshot["requested_environment"])
        if not requested:
            raise ValidationError("This submission requests no environment changes.")
    if not command.preview(
        "staff-" + action,
        {"current": current, "reason": reason},
        token,
        f"+buildadmin/{action} {submission.pk}=",
        text,
        suffix=f" # {reason}",
    ):
        return
    if action == "environment":
        services.approve_environment(
            command.caller, submission, expected_revision=submission.revision, reason=reason
        )
    elif action == "geometry":
        frontier.approve_geometry(
            command.caller, submission, expected_revision=submission.revision, reason=reason
        )
    else:
        services.review(
            command.caller,
            submission,
            expected_revision=submission.revision,
            outcome={"approve": "approved", "changes": "changes_requested", "decline": "declined"}[
                action
            ],
            reason=reason,
        )
    command.caller.msg(f"Submission {submission.pk}: {action} recorded.")


def _restore(command):
    target, token, reason = arguments(command)
    reason = reason_text(reason)
    if command.switch == "restore":
        item = _property(target)
        if item.state != "archived":
            raise ValidationError("Choose an archived property to restore.")
        current = state.property_state(item)
        text = f"Restore property {item.pk}: {item.name}; owner #{item.owner_id}.\nReason: {reason}"
        operation = lifecycle.restore
    else:
        item = _frontier(target)
        if item.state != "archived":
            raise ValidationError("Choose an archived frontier area to restore.")
        ids = item.archive_data.get("frontiers", [])
        current = {
            "group": [
                state.frontier_state(row)
                for row in Frontier.objects.filter(pk__in=ids).order_by("pk")
            ],
            "world": state.world_state(),
        }
        text = "Restore the complete frontier group: " + ", ".join(
            f"{row['id']}: {row['name']}" for row in current["group"]
        )
        text += f".\nReason: {reason}\nRestore affected homes separately after these streets."
        operation = frontier_lifecycle.restore
    if command.preview(
        "staff-" + command.switch,
        {"current": current, "reason": reason},
        token,
        f"+buildadmin/{command.switch} {item.pk}=",
        text,
        suffix=f" # {reason}",
    ):
        operation(command.caller, item, reason=reason)
        command.caller.msg(f"{item.name} restored.")


def _apply(command):
    target, token, reason = arguments(command)
    if reason:
        raise ValidationError(
            "The proposal already records its reason. Use +buildadmin/apply <change>."
        )
    change = PassageChange.objects.select_related("agreement__parent", "agreement__child").get(
        pk=support.number(target)
    )
    attachments._current_change(change)
    if not change.parent_accepted or not change.child_accepted:
        raise ValidationError(
            "Both current owners must accept through +passage before staff applies this change."
        )
    current = {
        "change": change.pk,
        "route": change.route,
        "previous": change.previous_route,
        "parent": state.property_state(change.agreement.parent),
        "child": state.property_state(change.agreement.child),
        "parent_accepted": change.parent_accepted,
        "child_accepted": change.child_accepted,
        "wording": change.wording,
        "reason": change.reason,
        "state": change.state,
    }
    text = f"Apply passage change {change.pk}: rooms {change.route['rooms']}. Both owners accepted.\n{change.reason}\n{change.wording}"
    if command.preview(
        "staff-apply-passage", current, token, f"+buildadmin/apply {change.pk}=", text
    ):
        attachments.apply_passage(command.caller, change)
        command.caller.msg("Replacement passage applied.")


def run_staff(command):
    """Authorize before looking up any staff target or persistent draft."""
    actor, action = command.caller, command.switch
    lifecycle._staff(actor)
    if action in {"", "list", "show"}:
        value = command.bare()
        if value:
            submission = BuildSubmission.objects.get(pk=support.number(value))
            actor.msg(
                f"Submission {submission.pk}: {submission.project.name}\n"
                + support.candidate_text(submission.snapshot)
            )
        else:
            actor.msg(
                "\n".join(
                    f"{row.pk}: {row.project.name}; revision {row.revision}"
                    for row in BuildSubmission.objects.filter(
                        project__state="submitted",
                        review__isnull=True,
                        pk=Subquery(
                            BuildSubmission.objects.filter(project_id=OuterRef("project_id"))
                            .order_by("-revision")
                            .values("pk")[:1]
                        ),
                    )
                    .select_related("project")
                    .order_by("pk")
                )
                or "No Building submissions await review."
            )
    elif action in STARTS:
        _start(command)
    elif action in {
        "stock",
        "grants",
        "children",
        "frontiers",
        "properties",
        "replacement",
        "unreplace",
        "reason",
    }:
        _field(command)
    elif action == "draft":
        command.empty()
        plan = _draft(actor)
        try:
            shown = _summary(plan, _plan_state(plan))
        except ValidationError as exc:
            fields = {
                key: value
                for key, value in plan.items()
                if key
                not in {"nonce", "revision", "expected_owner", "expected_steward", "assigned"}
            }
            shown = "\n".join(
                f"{key.replace('_', ' ').title()}: {value}" for key, value in fields.items()
            )
            shown += "\nBefore confirmation: " + " ".join(exc.messages)
        actor.msg(shown)
    elif action == "finish":
        _finish(command)
    elif action == "cancel":
        command.empty()
        if not actor.attributes.has(DRAFT_KEY):
            raise ValidationError("You have no staff draft to cancel.")
        actor.attributes.remove(DRAFT_KEY)
        actor.msg("Staff draft cancelled.")
    elif action in {"approve", "changes", "decline", "environment", "geometry"}:
        _review(command)
    elif action in {"restore", "frontierrestore"}:
        _restore(command)
    elif action == "apply":
        _apply(command)
    elif action in {"policy", "region"}:
        target, value, reason = arguments(command)
        if not value:
            raise ValidationError(f"Use +buildadmin/{action} <target>=<policy>.")
        if action == "region":
            if not apps.is_installed("evennia_regions"):
                raise ValidationError("Region policies are unavailable without Regions.")
            region = support.select(
                apps.get_model("evennia_regions", "Region").objects.filter(is_archived=False),
                target,
            )
            target = region.pk
        else:
            target = support.world_room(actor, target)
        set_policy(actor, target, value.casefold(), region=action == "region", reason=reason)
        actor.msg("Building policy updated.")
    elif action == "quiet":
        command.empty()
        lifecycle.check_quiet()
        frontier_lifecycle.check_quiet()
        lines = [
            f"Property {row.property_id}: {row.property.name}; owner {row.property.owner_name}; {row.reason}."
            for row in lifecycle.quiet_list(actor)
        ]
        lines += [
            f"Frontier room #{row.room.object_id}: {row.room.frontier.name}; steward {row.room.steward_name or 'staff'}."
            for row in frontier_lifecycle.quiet_list(actor)
        ]
        actor.msg(
            "\n".join(lines) or "No quiet-review flags. No ownership or stewardship rights changed."
        )
