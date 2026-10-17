# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Patterns: crafter knowledge with lineage, forward-only stages and shared-scene teaching."""

from datetime import timedelta

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from evennia.objects.models import ObjectDB

from evennia_links.characters import is_playable, same_account
from evennia_links.guests import is_guest
from evennia_links.runtime import get

from . import conf
from .behaviours import behaviour, text
from .errors import CraftingError
from .models import (
    NicheDefinition,
    Pattern,
    PatternKnowledge,
    PatternOffer,
    PatternStageChange,
    PatternThreadGrant,
)

STAGES = [choice.value for choice in Pattern.Stage]
TEACHABLE = {Pattern.Stage.SPREADING, Pattern.Stage.COMMON}


def visible(actor):
    return conf.visible(actor) and (get("RP_CRAFTING_PATTERNS_REVEALED") or conf.is_staff(actor))


def _require(actor, *, staff=False):
    if not visible(actor):
        raise CraftingError("Patterns are unavailable.")
    if staff and not conf.is_staff(actor):
        raise CraftingError("Only staff may manage Patterns.")
    if is_guest(actor):
        raise CraftingError("Guests cannot learn or teach Patterns.")


def find(value, *, archived=False):
    value = (value or "").strip()
    rows = Pattern.objects.all() if archived else Pattern.objects.filter(archived=False)
    pattern = rows.filter(key=value.lower()).first() or next(
        (row for row in rows if row.name.casefold() == value.casefold()), None
    )
    if pattern is None:
        raise CraftingError("Unknown Pattern.")
    return pattern


def _reserve(*characters):
    """Characters before Patterns, as journals and letters lock; a write comes first
    so SQLite takes its writer lock before any read in the transaction."""
    for character in sorted(characters, key=lambda character: character.pk):
        ObjectDB.objects.filter(pk=character.pk).update(db_key=F("db_key"))
        ObjectDB.objects.select_for_update().get(pk=character.pk)


def _fresh(pattern):
    """Services trust the locked database row, never a caller's possibly stale instance."""
    Pattern.objects.filter(pk=pattern.pk).update(key=F("key"))
    return Pattern.objects.select_for_update().get(pk=pattern.pk)


def knowledge(character, pattern):
    return PatternKnowledge.objects.filter(pattern=pattern, character=character).first()


def known_by(pattern):
    return PatternKnowledge.objects.filter(pattern=pattern).count()


def _log(pattern, to_stage, changed_by, reason):
    PatternStageChange.objects.create(
        pattern=pattern,
        from_stage=pattern.stage,
        to_stage=to_stage,
        changed_by_id=changed_by.pk if changed_by else None,
        reason=reason,
    )
    pattern.stage = to_stage
    pattern.stage_changed_at = timezone.now()
    pattern.save(update_fields=["stage", "stage_changed_at"])


def current_stage(pattern):
    """Apply the Spreading backstop clock as currently tuned; stages never move back."""
    if pattern.stage != Pattern.Stage.SPREADING:
        return pattern.stage
    days = get("RP_CRAFTING_PATTERN_COMMON_DAYS")
    if timezone.now() - pattern.stage_changed_at < timedelta(days=days):
        return pattern.stage
    with transaction.atomic():
        locked = _fresh(pattern)
        if locked.stage == Pattern.Stage.SPREADING:
            _log(locked, Pattern.Stage.COMMON, None, f"Backstop clock ({days} days)")
    pattern.refresh_from_db()
    return pattern.stage


@transaction.atomic
def advance(actor, pattern, reason=""):
    locked = _fresh(pattern)
    _require(actor, staff=True)
    current_stage(locked)
    position = STAGES.index(locked.stage)
    if position == len(STAGES) - 1:
        raise CraftingError("That Pattern is already Common.")
    _log(locked, STAGES[position + 1], actor, text(reason, "Reason", 255) or "Staff advance")
    return locked


def validate_niches(values):
    if not isinstance(values, list) or not values or len(values) != len(set(values)):
        raise CraftingError("List one or more distinct niche keys.")
    known = set(NicheDefinition.objects.filter(key__in=values).values_list("key", flat=True))
    if set(values) - known:
        raise CraftingError("Every Pattern niche must be an existing niche key.")
    return list(values)


def validate_combinations(value):
    """Pattern combinations use the same complete verb sets as the global allow-list."""
    if not isinstance(value, dict):
        raise CraftingError("Pattern combinations must be a mapping.")
    result = {}
    for lifecycle, choices in value.items():
        if behaviour(lifecycle).role != "lifecycle":
            raise CraftingError("Pattern combinations start from a lifecycle.")
        if not isinstance(choices, (list, tuple)):
            raise CraftingError("Pattern combinations must list complete verb sets.")
        sets = []
        for choice in choices:
            if (
                not isinstance(choice, (list, tuple))
                or len(set(choice)) != len(choice)
                or any(not isinstance(key, str) or behaviour(key).role != "verb" for key in choice)
            ):
                raise CraftingError("Pattern combinations must list complete verb sets.")
            if sorted(choice) not in sets:
                sets.append(sorted(choice))
        if sets:
            result[lifecycle] = sets
    return result


def parse_combination(value):
    """`wearable:readable+activatable` → (lifecycle, sorted verbs)."""
    lifecycle, _, verbs = (value or "").partition(":")
    keys = sorted(key.strip() for key in verbs.split("+") if key.strip())
    validate_combinations({lifecycle.strip(): [keys]})
    return lifecycle.strip(), keys


def for_craft(actor, key, primary):
    """The Pattern a craft names, if the crafter may work in it with this niche."""
    if key is None:
        return None
    if not visible(actor):
        raise CraftingError("Patterns are unavailable.")
    pattern = find(key)
    if knowledge(actor, pattern) is None:
        raise CraftingError("You don't know that Pattern.")
    if primary not in pattern.niches:
        raise CraftingError("That Pattern doesn't serve this niche.")
    return pattern


def _learn(character, pattern, via, **fields):
    """Create knowledge under the character lock; repeated grants are harmless."""
    _reserve(character)
    existing = knowledge(character, pattern)
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            row = PatternKnowledge.objects.create(
                pattern=pattern,
                character=character,
                character_name=character.key,
                learned_via=via,
                **fields,
            )
    except IntegrityError:
        return knowledge(character, pattern), False
    PatternOffer.objects.filter(pattern=pattern, student_id=character.pk).delete()
    return row, True


@transaction.atomic
def create(actor, key, name, description=""):
    _reserve(actor)
    _require(actor, staff=True)
    key = (key or "").strip().lower()
    try:
        validate_slug(key)
    except ValidationError:
        raise CraftingError("Pattern keys use letters, numbers, hyphens and underscores.") from None
    if len(key) > 80:
        raise CraftingError("Pattern keys must contain 1-80 characters.")
    if Pattern.objects.filter(key=key).exists():
        raise CraftingError("That Pattern key is taken; keys are permanent.")
    return Pattern.objects.create(
        key=key,
        name=text(name, "Pattern name", 80, required=True),
        description=text(description, "Description", 2000),
        stage_changed_at=timezone.now(),
        created_by_id=actor.pk,
    )


@transaction.atomic
def edit(actor, pattern, **changes):
    """Staff edits; existing items keep the name and combinations captured at craft."""
    locked = _fresh(pattern)
    _require(actor, staff=True)
    if "name" in changes:
        locked.name = text(changes["name"], "Pattern name", 80, required=True)
    if "description" in changes:
        locked.description = text(changes["description"], "Description", 2000)
    if "niches" in changes:
        locked.niches = validate_niches(changes["niches"])
    if "combinations" in changes:
        locked.combinations = validate_combinations(changes["combinations"])
    if "archived" in changes:
        locked.archived = bool(changes["archived"])
    locked.save()
    return locked


@transaction.atomic
def grant(actor, pattern, character):
    _reserve(character)
    pattern = _fresh(pattern)
    _require(actor, staff=True)
    if pattern.archived:
        raise CraftingError("That Pattern is archived.")
    if not is_playable(character):
        raise CraftingError("Grant Patterns to a playable character.")
    return _learn(character, pattern, PatternKnowledge.Via.STAFF, granted_by_id=actor.pk)


def _thread(thread_id):
    if not apps.is_installed("evennia_plots"):
        raise CraftingError("Plot thread grants need evennia-plots.")
    # Thread before Pattern, as in conclusion; the write reserves SQLite's writer.
    model = apps.get_model("evennia_plots", "PlotThread")
    model.objects.filter(pk=thread_id).update(name=F("name"))
    return model.objects.select_for_update().filter(pk=thread_id).first()


@transaction.atomic
def attach(actor, pattern, thread_id):
    """Grant on conclusion; the first attached thread is the Pattern's origin."""
    thread = _thread(thread_id)
    _require(actor, staff=True)
    if thread is None or thread.status not in {"proposed", "active"}:
        raise CraftingError("Attach Patterns to a proposed or active plot thread.")
    locked = _fresh(pattern)
    if locked.archived:
        raise CraftingError("That Pattern is archived.")
    row, created = PatternThreadGrant.objects.get_or_create(
        pattern=locked,
        thread_id=thread.pk,
        defaults={"thread_name": thread.name, "granted_by_id": actor.pk},
    )
    if not created:
        raise CraftingError("That thread already grants this Pattern.")
    if locked.origin_thread_id is None:
        locked.origin_thread_id = thread.pk
        locked.save(update_fields=["origin_thread_id"])
    return row


@transaction.atomic
def on_concluded(sender, thread, **kwargs):
    """Inside the conclusion lock: grant active participants, then leave Recovered."""
    grants = list(
        PatternThreadGrant.objects.select_for_update()
        .filter(thread_id=thread.pk, applied_at__isnull=True)
        .select_related("pattern")
        .order_by("pk")
    )
    ids = sorted(thread.participants.filter(is_active=True).values_list("character_id", flat=True))
    characters = [
        character
        for character in ObjectDB.objects.filter(pk__in=[pk for pk in ids if pk]).order_by("pk")
        if is_playable(character)
    ]
    for row in grants:
        if row.pattern.archived:
            continue
        for character in characters:
            _learn(character, row.pattern, PatternKnowledge.Via.THREAD, thread_id=thread.pk)
        row.recipients = [{"id": c.pk, "name": c.key} for c in characters]
        row.applied_at = timezone.now()
        row.save(update_fields=["recipients", "applied_at"])
    for pattern in Pattern.objects.select_for_update().filter(
        origin_thread_id=thread.pk, stage=Pattern.Stage.RECOVERED
    ):
        _log(pattern, Pattern.Stage.SPREADING, None, f"Origin thread #{thread.pk} concluded")


def shared_scene(teacher, student):
    """The most recent scene both posed in: active, or closed within the teaching window."""
    if not apps.is_installed("evennia_scenes"):
        raise CraftingError("Teaching needs evennia-scenes.")
    participant = apps.get_model("evennia_scenes", "SceneParticipant")
    posed = participant.objects.filter(role="participant", pose_count__gte=1)
    window = timezone.now() - timedelta(days=get("RP_CRAFTING_PATTERN_TEACH_DAYS"))
    return (
        posed.filter(
            character_id=student.pk,
            scene_id__in=posed.filter(character_id=teacher.pk).values("scene_id"),
            scene__is_archived=False,
        )
        .filter(
            Q(scene__status__in=["open", "active"])
            | Q(scene__status="closed", scene__ended_at__gte=window)
        )
        .order_by("-scene_id")
        .values_list("scene_id", flat=True)
        .first()
    )


def _teaching(teacher, student, pattern):
    if pattern.archived:
        raise CraftingError("That Pattern is archived.")
    if teacher.pk == student.pk:
        raise CraftingError("Teach someone else.")
    if is_guest(teacher) or is_guest(student):
        raise CraftingError("Guests cannot learn or teach Patterns.")
    if knowledge(teacher, pattern) is None:
        raise CraftingError("You don't know that Pattern.")
    if current_stage(pattern) not in TEACHABLE:
        raise CraftingError("A Recovered Pattern can't be taught yet.")
    if knowledge(student, pattern) is not None:
        raise CraftingError(f"{student.key} already knows {pattern.name}.")
    if same_account(teacher, student):
        raise CraftingError("Characters on the same account can't teach each other.")
    scene = shared_scene(teacher, student)
    if scene is None:
        days = get("RP_CRAFTING_PATTERN_TEACH_DAYS")
        raise CraftingError(
            f"Teaching needs a logged scene you both posed in, active or closed within {days} days."
        )
    return scene


@transaction.atomic
def offer(teacher, student, pattern):
    _reserve(teacher)
    pattern = _fresh(pattern)
    _require(teacher)
    if not visible(student):
        raise CraftingError("They can't learn Patterns.")
    _teaching(teacher, student, pattern)
    row, created = PatternOffer.objects.get_or_create(
        pattern=pattern,
        teacher_id=teacher.pk,
        student_id=student.pk,
        defaults={"teacher_name": teacher.key},
    )
    if not created:
        raise CraftingError("You've already offered to teach them that Pattern.")
    return row


def offers(student):
    return list(
        PatternOffer.objects.filter(student_id=student.pk)
        .select_related("pattern")
        .order_by("created", "pk")
    )


def _pending(student, pattern, teacher=None):
    rows = PatternOffer.objects.filter(student_id=student.pk, pattern=pattern)
    if teacher is not None:
        rows = rows.filter(teacher_id=teacher.pk)
    row = rows.order_by("created", "pk").first()
    if row is None:
        raise CraftingError("Nobody has offered to teach you that Pattern.")
    return row


@transaction.atomic
def accept(student, pattern, teacher=None):
    """Revalidate the offer in full; acceptance is the student's own action."""
    _reserve(student)
    pattern = _fresh(pattern)
    _require(student)
    row = _pending(student, pattern, teacher)
    source = ObjectDB.objects.filter(pk=row.teacher_id).first()
    if source is None:
        row.delete()
        raise CraftingError("That teacher is gone.")
    scene = _teaching(source, student, pattern)
    learned, _ = _learn(
        student,
        pattern,
        PatternKnowledge.Via.TAUGHT,
        taught_by_id=source.pk,
        taught_by_name=source.key,
        teaching_scene_id=scene,
    )
    return learned


@transaction.atomic
def decline(student, pattern):
    _reserve(student)
    _require(student)
    deleted, _ = PatternOffer.objects.filter(student_id=student.pk, pattern=pattern).delete()
    if not deleted:
        raise CraftingError("Nobody has offered to teach you that Pattern.")


def describe_source(row):
    if row.learned_via == PatternKnowledge.Via.TAUGHT:
        scene = f" in scene #{row.teaching_scene_id}" if row.teaching_scene_id else ""
        return f"taught by {row.taught_by_name}{scene}"
    if row.learned_via == PatternKnowledge.Via.THREAD:
        grant = PatternThreadGrant.objects.filter(
            pattern_id=row.pattern_id, thread_id=row.thread_id
        ).first()
        return f"recovered in {grant.thread_name if grant else f'thread #{row.thread_id}'}"
    return "granted by staff"


def lineage(row):
    """The chain of teachers, as far as soft references and knowledge rows survive."""
    links, seen = [f"{row.character_name}: {describe_source(row)}"], {row.character_id}
    while row.learned_via == PatternKnowledge.Via.TAUGHT and row.taught_by_id not in seen:
        seen.add(row.taught_by_id)
        row = PatternKnowledge.objects.filter(
            pattern_id=row.pattern_id, character_id=row.taught_by_id
        ).first()
        if row is None:
            break
        links.append(f"{row.character_name}: {describe_source(row)}")
    return links


def combinations_text(pattern):
    return (
        "; ".join(
            f"{lifecycle} + {' + '.join(verbs) or 'no verbs'}"
            for lifecycle, choices in sorted(pattern.combinations.items())
            for verbs in choices
        )
        or "none (hallmark only)"
    )


def info(looker, pattern):
    stage = current_stage(pattern)
    rows = [
        f"{pattern.name} ({pattern.key}) — {Pattern.Stage(stage).label}"
        + (" [archived]" if pattern.archived else ""),
        pattern.description or "No description.",
        f"Niches: {', '.join(pattern.niches) or 'none'}.",
        f"Unlocks: {combinations_text(pattern)}.",
        f"Known by {known_by(pattern)} crafter(s).",
    ]
    row = knowledge(looker, pattern)
    if row:
        rows.append("Your lineage: " + " ← ".join(lineage(row)) + ".")
    return "\n".join(rows)


def roster(actor, pattern):
    _require(actor, staff=True)
    rows = [f"{pattern.name}: stage history and knowers (OOC)."]
    rows += [
        f"{change.created:%Y-%m-%d} {change.from_stage} → {change.to_stage}: {change.reason}"
        for change in pattern.stage_changes.order_by("pk")
    ]
    rows += [
        f"#{row.character_id} {' ← '.join(lineage(row))}"
        for row in pattern.knowledge.order_by("learned_at", "pk")
    ]
    rows += [
        f"Thread #{row.thread_id} {row.thread_name}: "
        + (f"applied {row.applied_at:%Y-%m-%d}" if row.applied_at else "pending")
        for row in pattern.thread_grants.order_by("pk")
    ]
    return "\n".join(rows)
