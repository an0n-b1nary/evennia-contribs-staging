# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
Thread and owner services for evennia_plots.

Every rule about who may do what to a plot's threads and owners lives here,
so the ``+plot`` command and the web views cannot drift apart. Each action
checks permission and state, then raises ``ThreadError`` with a player-facing
message when it doesn't apply.

Who may do what:

=====================  =====================================================
Add a thread           Owners and staff under any policy; anyone who can
                       link under ``open``. Plot must be proposed or active.
Request a thread       Anyone who can link, under ``request``.
Accept / decline       Owners and staff.
Withdraw a request     The requester.
Hold, seal, drop       Owners and staff.
Resolve                Held: owners and staff. Not held: also the thread's
                       creator and its leads.
Reopen, reveal         Owners and staff.
Lead / interest        Anyone who can view the plot, on an open thread.
Carry a loose end      Someone who manages both plots, into a declared sequel.
=====================  =====================================================

When staff take an owner's action on a plot they don't own, the action is
recorded in the plot's ``staff_log``.

Threads have no effect on XP.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from evennia_plots.models import (
    PlotOwner,
    PlotThread,
    StoryThread,
    StoryThreadAnswerVersion,
    StoryThreadInterest,
    ThreadLink,
)
from evennia_plots.permissions import is_plot_staff

TITLE_MAX = 200
DETAIL_MAX = 500
RESOLUTION_MAX = 1000
DECLINE_REASON_MAX = 500

_PLOT_LIVE = (PlotThread.Status.PROPOSED, PlotThread.Status.ACTIVE)
_FINISHED = (
    StoryThread.Status.RESOLVED,
    StoryThread.Status.DROPPED,
    StoryThread.Status.LOOSE_END,
    StoryThread.Status.CARRIED,
)


class ThreadError(Exception):
    """A thread or owner action that the actor may not take, or that doesn't apply."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _name(character):
    return character.key if character is not None else "System"


def _note_staff(plot, actor, action, detail=""):
    """Log an owner's action taken by staff who don't own the plot (P11)."""
    if actor is not None and is_plot_staff(actor) and not plot.is_owner(actor):
        plot.log_staff_action(actor, action, detail)


def _notify(characters, text, skip=None):
    for character in characters:
        if character is None or (skip is not None and character.pk == skip.pk):
            continue
        try:
            character.msg(text)
        except Exception:
            continue


def _owners(plot):
    return [owner.character for owner in plot.owners.select_related("character")]


def _require_manager(plot, actor, what):
    if not plot.can_manage(actor):
        raise ThreadError(f"Only the plot's owners (or staff) can {what}.")


def _require_status(thread, *statuses, what):
    if thread.status not in statuses:
        raise ThreadError(f"Thread {thread.ref} is {thread.get_status_display().lower()}; {what}.")


def _clean(text, limit, label, required=True):
    text = (text or "").strip()
    if required and not text:
        raise ThreadError(f"The {label} can't be empty.")
    if len(text) > limit:
        raise ThreadError(f"The {label} must be {limit} characters or fewer.")
    return text


# ---------------------------------------------------------------------------
# Predicates (used by actions and by the UI to offer them)
# ---------------------------------------------------------------------------


def can_add_directly(plot, actor):
    """True if *actor* may add an open thread to *plot* without a request."""
    if actor is None or plot.status not in _PLOT_LIVE:
        return False
    if plot.can_manage(actor):
        return True
    return plot.thread_policy == PlotThread.ThreadPolicy.OPEN and plot.can_link(actor)


def can_request(plot, actor):
    """True if *actor* would add a thread to *plot* as a request."""
    if actor is None or plot.can_manage(actor):
        return False
    return plot.thread_policy == PlotThread.ThreadPolicy.REQUEST and plot.can_link(actor)


def can_resolve(thread, actor):
    if actor is None or thread.status != StoryThread.Status.OPEN:
        return False
    if thread.plot.can_manage(actor):
        return True
    if thread.is_held:
        return False
    if thread.created_by_id == actor.pk:
        return True
    return thread.interests.filter(character=actor, is_lead=True).exists()


def can_follow(thread, actor):
    """True if *actor* may mark lead or interest on *thread*."""
    return (
        actor is not None
        and thread.status == StoryThread.Status.OPEN
        and thread.plot.status in _PLOT_LIVE
        and thread.plot.can_view(actor)
    )


def can_read_answer(thread, character):
    """True if *character* may read *thread*'s sealed answer and its history."""
    if not thread.has_sealed_answer:
        return False
    if character is not None and thread.plot.can_manage(character):
        return True
    return thread.sealed_answer_revealed and thread.plot.can_view(character)


def visible_threads(plot, character):
    """The plot's threads *character* may see, in number order.

    Every thread title is public to anyone who can see the plot (there are no
    hidden threads). Pending and declined requests are shown only to the
    plot's managers and to the requester, to keep the plot page uncluttered.
    """
    threads = plot.story_threads.select_related("plot", "carried_to__plot").order_by("number")
    if character is not None and plot.can_manage(character):
        return list(threads)
    pending = (StoryThread.Status.REQUESTED, StoryThread.Status.DECLINED)
    return [
        thread
        for thread in threads
        if thread.status not in pending
        or (character is not None and thread.created_by_id == character.pk)
    ]


def available_actions(thread, character):
    """Return the set of action names *character* may take on *thread* now."""
    actions = set()
    if character is None:
        return actions
    plot = thread.plot
    manages = plot.can_manage(character)
    status = thread.status
    if status == StoryThread.Status.REQUESTED:
        if manages:
            actions |= {"accept", "decline"}
        if thread.created_by_id == character.pk:
            actions.add("withdraw")
    if status == StoryThread.Status.OPEN:
        if manages:
            actions |= {"hold" if not thread.is_held else "unhold", "seal", "drop"}
        if can_resolve(thread, character):
            actions.add("resolve")
        if can_follow(thread, character):
            interest = thread.interests.filter(character=character).first()
            actions.add("unlead" if interest and interest.is_lead else "lead")
            actions.add("uninterest" if interest else "interest")
    if status in (StoryThread.Status.REQUESTED, StoryThread.Status.OPEN) and (
        manages or thread.created_by_id == character.pk
    ):
        actions.add("detail")
    reopenable = (StoryThread.Status.RESOLVED, StoryThread.Status.DROPPED)
    if manages and status in reopenable and plot.status in _PLOT_LIVE:
        actions.add("reopen")
    if manages and thread.answer_is_sealed and status in _FINISHED:
        actions.add("reveal")
    if manages and status == StoryThread.Status.LOOSE_END:
        actions.add("carry")
    if can_read_answer(thread, character):
        actions.add("answer")
    return actions


# ---------------------------------------------------------------------------
# Adding, requesting and deciding
# ---------------------------------------------------------------------------


def add_thread(plot, actor, title, detail=""):
    """Add a thread to *plot*, or request one when the plot's policy says so.

    Returns:
        StoryThread: open when added directly, requested otherwise.
    """
    title = _clean(title, TITLE_MAX, "title")
    detail = _clean(detail, DETAIL_MAX, "detail", required=False)
    if can_add_directly(plot, actor):
        status = StoryThread.Status.OPEN
    elif can_request(plot, actor):
        status = StoryThread.Status.REQUESTED
    elif plot.status not in _PLOT_LIVE:
        raise ThreadError(f"Plot #{plot.plot_number} is {plot.get_status_display().lower()}.")
    elif plot.thread_policy == PlotThread.ThreadPolicy.OWNERS:
        raise ThreadError(f"Only the owners of plot #{plot.plot_number} add its threads.")
    else:
        raise ThreadError(f"You can't add threads to plot #{plot.plot_number}.")

    for _attempt in range(3):
        try:
            with transaction.atomic():
                thread = StoryThread.objects.create(
                    plot=plot,
                    number=StoryThread.next_number(plot),
                    title=title,
                    detail=detail,
                    status=status,
                    created_by=actor,
                    created_by_name=_name(actor),
                )
            break
        except IntegrityError:
            continue
    else:
        raise ThreadError("Someone else added a thread at the same moment. Try again.")

    if status == StoryThread.Status.REQUESTED:
        _notify(
            _owners(plot),
            f"|y[Plot]|n {_name(actor)} asks to open thread {thread.ref} on "
            f"|w{plot.name}|n: {thread.title}\n"
            f"Accept with |w+thread/accept {thread.ref}|n or decline with "
            f"|w+thread/decline {thread.ref}=<reason>|n.",
            skip=actor,
        )
    else:
        _note_staff(plot, actor, "added thread", f"{thread.ref} {thread.title}")
    return thread


def accept(thread, actor):
    plot = thread.plot
    _require_manager(plot, actor, "accept thread requests")
    _require_status(thread, StoryThread.Status.REQUESTED, what="only requests can be accepted")
    if plot.status not in _PLOT_LIVE:
        raise ThreadError(f"Plot #{plot.plot_number} is {plot.get_status_display().lower()}.")
    thread.status = StoryThread.Status.OPEN
    thread.decided_by = actor
    thread.decided_by_name = _name(actor)
    thread.save(update_fields=["status", "decided_by", "decided_by_name", "updated_at"])
    _note_staff(plot, actor, "accepted thread request", f"{thread.ref} {thread.title}")
    _notify(
        [thread.created_by],
        f"|y[Plot]|n Your thread {thread.ref} on |w{plot.name}|n was accepted: {thread.title}",
        skip=actor,
    )
    return thread


def decline(thread, actor, reason=""):
    plot = thread.plot
    _require_manager(plot, actor, "decline thread requests")
    _require_status(thread, StoryThread.Status.REQUESTED, what="only requests can be declined")
    thread.status = StoryThread.Status.DECLINED
    thread.decline_reason = _clean(reason, DECLINE_REASON_MAX, "reason", required=False)
    thread.decided_by = actor
    thread.decided_by_name = _name(actor)
    thread.save(
        update_fields=["status", "decline_reason", "decided_by", "decided_by_name", "updated_at"]
    )
    _note_staff(plot, actor, "declined thread request", f"{thread.ref} {thread.title}")
    because = f" ({thread.decline_reason})" if thread.decline_reason else ""
    _notify(
        [thread.created_by],
        f"|y[Plot]|n Your thread request {thread.ref} on |w{plot.name}|n was declined{because}.",
        skip=actor,
    )
    return thread


def withdraw(thread, actor):
    """Delete the actor's own pending request. Nothing else is preserved."""
    _require_status(thread, StoryThread.Status.REQUESTED, what="only requests can be withdrawn")
    if actor is None or thread.created_by_id != actor.pk:
        raise ThreadError("Only the character who asked can withdraw a request.")
    ref = thread.ref
    thread.delete()
    return ref


def set_detail(thread, actor, detail):
    if not (thread.plot.can_manage(actor) or (actor and thread.created_by_id == actor.pk)):
        raise ThreadError("Only the plot's owners (or the thread's creator) can edit its detail.")
    _require_status(
        thread,
        StoryThread.Status.REQUESTED,
        StoryThread.Status.OPEN,
        what="its detail can no longer change",
    )
    thread.detail = _clean(detail, DETAIL_MAX, "detail", required=False)
    thread.save(update_fields=["detail", "updated_at"])
    return thread


# ---------------------------------------------------------------------------
# Holding and sealed answers
# ---------------------------------------------------------------------------


def set_held(thread, actor, held):
    plot = thread.plot
    _require_manager(plot, actor, "mark threads held")
    _require_status(thread, StoryThread.Status.OPEN, what="only open threads can be held")
    if not held and thread.has_sealed_answer:
        raise ThreadError(
            f"{thread.ref} has a sealed answer. Clear it first with "
            f"|w+thread/seal {thread.ref}=|n (an empty answer)."
        )
    thread.is_held = held
    thread.save(update_fields=["is_held", "updated_at"])
    _note_staff(plot, actor, "held thread" if held else "released thread", thread.ref)
    return thread


def seal(thread, actor, answer):
    """Write, replace or (with an empty answer) clear a thread's sealed answer.

    Sealing marks the thread held. The previous wording is kept as a version.
    """
    plot = thread.plot
    _require_manager(plot, actor, "seal an answer")
    _require_status(thread, StoryThread.Status.OPEN, what="only open threads can be sealed")
    answer = (answer or "").strip()
    if answer == thread.sealed_answer.strip() and not thread.sealed_answer_revealed:
        return thread
    with transaction.atomic():
        if thread.has_sealed_answer:
            StoryThreadAnswerVersion.create_version(
                parent=thread, content=thread.sealed_answer, editor=actor
            )
        thread.sealed_answer = answer
        thread.sealed_answer_revealed = False
        if answer:
            thread.is_held = True
            if thread.sealed_at is None:
                thread.sealed_at = timezone.now()
        thread.save(
            update_fields=[
                "sealed_answer",
                "sealed_answer_revealed",
                "is_held",
                "sealed_at",
                "updated_at",
            ]
        )
    _note_staff(plot, actor, "sealed answer" if answer else "cleared sealed answer", thread.ref)
    return thread


def reveal(thread, actor):
    plot = thread.plot
    _require_manager(plot, actor, "reveal a sealed answer")
    if not thread.has_sealed_answer:
        raise ThreadError(f"{thread.ref} has no sealed answer.")
    if thread.sealed_answer_revealed:
        raise ThreadError(f"The answer to {thread.ref} is already revealed.")
    if thread.status not in _FINISHED:
        raise ThreadError(f"Resolve or drop {thread.ref} before revealing its answer.")
    thread.sealed_answer_revealed = True
    thread.save(update_fields=["sealed_answer_revealed", "updated_at"])
    _note_staff(plot, actor, "revealed sealed answer", thread.ref)
    return thread


# ---------------------------------------------------------------------------
# Resolving, dropping, reopening
# ---------------------------------------------------------------------------


def resolve(thread, actor, summary, reveal_answer=False):
    """Resolve an open thread with an OOC summary, optionally revealing its answer."""
    plot = thread.plot
    _require_status(thread, StoryThread.Status.OPEN, what="only open threads can be resolved")
    if not can_resolve(thread, actor):
        if thread.is_held:
            raise ThreadError(f"{thread.ref} is held: only the plot's owners can resolve it.")
        raise ThreadError(
            f"Only the plot's owners, the thread's creator or its leads can resolve {thread.ref}."
        )
    thread.resolution = _clean(summary, RESOLUTION_MAX, "summary")
    thread.status = StoryThread.Status.RESOLVED
    thread.resolved_by = actor
    thread.resolved_by_name = _name(actor)
    thread.resolved_at = timezone.now()
    fields = ["resolution", "status", "resolved_by", "resolved_by_name", "resolved_at"]
    if reveal_answer and thread.answer_is_sealed:
        thread.sealed_answer_revealed = True
        fields.append("sealed_answer_revealed")
    thread.save(update_fields=[*fields, "updated_at"])
    if thread.is_held:
        _note_staff(plot, actor, "resolved held thread", thread.ref)
    return thread


def drop(thread, actor, reveal_answer=False):
    plot = thread.plot
    _require_manager(plot, actor, "drop threads")
    _require_status(thread, StoryThread.Status.OPEN, what="only open threads can be dropped")
    thread.status = StoryThread.Status.DROPPED
    thread.resolved_by = actor
    thread.resolved_by_name = _name(actor)
    thread.resolved_at = timezone.now()
    fields = ["status", "resolved_by", "resolved_by_name", "resolved_at"]
    if reveal_answer and thread.answer_is_sealed:
        thread.sealed_answer_revealed = True
        fields.append("sealed_answer_revealed")
    thread.save(update_fields=[*fields, "updated_at"])
    _note_staff(plot, actor, "dropped thread", thread.ref)
    return thread


def reopen(thread, actor):
    plot = thread.plot
    _require_manager(plot, actor, "reopen threads")
    _require_status(
        thread,
        StoryThread.Status.RESOLVED,
        StoryThread.Status.DROPPED,
        what="only resolved or dropped threads can be reopened",
    )
    if plot.status not in _PLOT_LIVE:
        raise ThreadError(f"Plot #{plot.plot_number} is {plot.get_status_display().lower()}.")
    thread.status = StoryThread.Status.OPEN
    thread.resolution = ""
    thread.resolved_by = None
    thread.resolved_by_name = ""
    thread.resolved_at = None
    thread.save(
        update_fields=[
            "status",
            "resolution",
            "resolved_by",
            "resolved_by_name",
            "resolved_at",
            "updated_at",
        ]
    )
    _note_staff(plot, actor, "reopened thread", thread.ref)
    return thread


# ---------------------------------------------------------------------------
# Leads and interest
# ---------------------------------------------------------------------------


def toggle_lead(thread, actor):
    """Toggle *actor* as a lead on *thread*. Returns True if now leading."""
    if not can_follow(thread, actor):
        raise ThreadError(f"You can't lead {thread.ref} now.")
    interest, created = StoryThreadInterest.objects.get_or_create(
        thread=thread,
        character=actor,
        defaults={"character_name": actor.key, "is_lead": True},
    )
    if not created:
        interest.is_lead = not interest.is_lead
        interest.save(update_fields=["is_lead"])
    return interest.is_lead


def toggle_interest(thread, actor):
    """Toggle *actor*'s interest in *thread* (removing interest drops a lead too).

    Returns True if now interested.
    """
    if not can_follow(thread, actor):
        raise ThreadError(f"You can't follow {thread.ref} now.")
    deleted, _ = StoryThreadInterest.objects.filter(thread=thread, character=actor).delete()
    if deleted:
        return False
    StoryThreadInterest.objects.create(thread=thread, character=actor, character_name=actor.key)
    return True


# ---------------------------------------------------------------------------
# Carrying loose ends
# ---------------------------------------------------------------------------


def is_sequel(target, source):
    """True if *target* is declared a sequel of *source* (``+plot/sequel``)."""
    return ThreadLink.objects.filter(
        from_thread=target,
        to_thread=source,
        link_type=ThreadLink.LinkType.SEQUEL,
        is_accepted=True,
    ).exists()


def carry_targets(thread, actor):
    """Sequel plots *actor* could carry *thread* into."""
    if thread.status != StoryThread.Status.LOOSE_END or not thread.plot.can_manage(actor):
        return []
    sequel_ids = ThreadLink.objects.filter(
        to_thread=thread.plot,
        link_type=ThreadLink.LinkType.SEQUEL,
        is_accepted=True,
    ).values_list("from_thread_id", flat=True)
    return [
        plot
        for plot in PlotThread.objects.filter(pk__in=sequel_ids, status__in=_PLOT_LIVE).order_by(
            "plot_number"
        )
        if plot.can_manage(actor)
    ]


def carry(thread, actor, target):
    """Carry a loose end into *target*, a sequel plot, as a new open thread.

    The sealed answer travels only when every owner of *target* also owns the
    source plot (or it was already revealed), so it never reaches new eyes.

    Returns:
        tuple: (new StoryThread, bool answer_carried)
    """
    source = thread.plot
    _require_status(thread, StoryThread.Status.LOOSE_END, what="only loose ends can be carried")
    if target.pk == source.pk:
        raise ThreadError("Carry a loose end into a different plot.")
    if not (source.can_manage(actor) and target.can_manage(actor)):
        raise ThreadError("You must run both plots (or be staff) to carry a thread between them.")
    if target.status not in _PLOT_LIVE:
        raise ThreadError(f"Plot #{target.plot_number} is {target.get_status_display().lower()}.")
    if not is_sequel(target, source):
        raise ThreadError(
            f"Plot #{target.plot_number} isn't a sequel of #{source.plot_number}. "
            f"Declare it with |w+plot/sequel #{target.plot_number}=#{source.plot_number}|n."
        )
    answer_carried = thread.has_sealed_answer and (
        thread.sealed_answer_revealed or target.owner_ids() <= source.owner_ids()
    )
    with transaction.atomic():
        new = StoryThread.objects.create(
            plot=target,
            number=StoryThread.next_number(target),
            title=thread.title,
            detail=thread.detail,
            status=StoryThread.Status.OPEN,
            is_held=thread.is_held,
            sealed_answer=thread.sealed_answer if answer_carried else "",
            sealed_at=thread.sealed_at if answer_carried else None,
            sealed_answer_revealed=thread.sealed_answer_revealed if answer_carried else False,
            created_by=actor,
            created_by_name=_name(actor),
        )
        thread.status = StoryThread.Status.CARRIED
        thread.carried_to = new
        thread.save(update_fields=["status", "carried_to", "updated_at"])
    _note_staff(source, actor, "carried thread", f"{thread.ref} → {new.ref}")
    return new, answer_carried


# ---------------------------------------------------------------------------
# Owners and policy
# ---------------------------------------------------------------------------


def add_owner(plot, actor, character):
    _require_manager(plot, actor, "add owners")
    if plot.is_owner(character):
        raise ThreadError(f"{character.key} already owns plot #{plot.plot_number}.")
    owner = PlotOwner.objects.create(
        plot=plot,
        character=character,
        character_name=character.key,
        added_by=actor,
        added_by_name=_name(actor),
    )
    _note_staff(plot, actor, "added owner", character.key)
    _notify(
        [character],
        f"|y[Plot]|n {_name(actor)} made you an owner of |w{plot.name}|n (#{plot.plot_number}).",
        skip=actor,
    )
    return owner


def remove_owner(plot, actor, character):
    _require_manager(plot, actor, "remove owners")
    owner = plot.owners.filter(character=character).first()
    if owner is None:
        raise ThreadError(f"{character.key} doesn't own plot #{plot.plot_number}.")
    if plot.owners.count() <= 1 and not is_plot_staff(actor):
        raise ThreadError("A plot keeps at least one owner. Add another owner first.")
    owner.delete()
    _note_staff(plot, actor, "removed owner", character.key)
    return character


def set_policy(plot, actor, policy):
    _require_manager(plot, actor, "set the thread policy")
    if policy not in PlotThread.ThreadPolicy.values:
        raise ThreadError("Thread policy must be owners, request or open.")
    plot.thread_policy = policy
    plot.save(update_fields=["thread_policy"])
    _note_staff(plot, actor, "set thread policy", policy)
    return plot
