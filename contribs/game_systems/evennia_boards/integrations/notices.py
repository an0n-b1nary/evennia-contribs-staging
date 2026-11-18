# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Immutable Boards activity references and live Inbox presentation."""

from evennia_boards.models import Board, Post, Subscription
from evennia_links.notices import (
    ActorRef,
    Evaluation,
    NoticeAction,
    NoticeContext,
    NoticeEvent,
    RenderedNotice,
    StoredEvent,
    SubjectRef,
    authorize_context,
)

SOURCE = "boards"
POST_FIELDS = ("pk", "board_id", "author_id", "is_system_post", "created_at")


def event_for(subscription, post):
    """Reference a single active post with known system or character provenance."""
    post_id, board_id, author_id, system, created_at = post
    if board_id != subscription.board_id or system == (author_id is not None):
        return None
    return NoticeEvent(
        f"boards-{subscription.pk}-{post_id}",
        created_at,
        SubjectRef("board", str(board_id)),
        (ActorRef("character", author_id),) if author_id is not None else (),
        {
            "account": subscription.account_id,
            "subscription": subscription.pk,
            "board": board_id,
            "post": post_id,
        },
        replacement_key=f"board-{board_id}",
    )


def own_character_ids(account):
    """Characters on the account's playable list; their posts are not new to it."""
    try:
        return {obj.pk for obj in account.characters.all() if obj and obj.pk}
    except AttributeError:
        return set()


def _ids(events, field):
    return {value for event in events if type(value := event.payload.get(field)) is int}


class BoardNoticeSource:
    """Routine activity for an account's current subscription generation."""

    label = "Boards"

    def prepare(self, context):
        """Quietly discover activity before that connection's shared summary."""
        if authorize_context(NoticeContext(context.account, session=context.session)):
            from evennia_boards.notices import prepare_account

            prepare_account(context.account.pk)

    def evaluate(self, events, context):
        """Verify provenance and live subscription ownership; skip the account's own posts."""
        if not authorize_context(NoticeContext(context.account, session=context.session)):
            return {event.event_id: Evaluation("invalid") for event in events}
        subscriptions = (
            Subscription.objects.filter(
                pk__in=_ids(events, "subscription"), account_id=context.account.pk
            )
            .only("pk", "account_id", "board_id", "inbox_start_post_id")
            .in_bulk()
        )
        posts = {
            row[0]: row
            for row in Post.objects.filter(pk__in=_ids(events, "post")).values_list(*POST_FIELDS)
        }

        own = own_character_ids(context.account)
        outcomes = {}
        for event in events:
            payload = event.payload
            expected = None
            if all(
                type(payload.get(key)) is int
                for key in ("account", "subscription", "board", "post")
            ):
                subscription = subscriptions.get(payload["subscription"])
                post = posts.get(payload["post"])
                if (
                    subscription
                    and post
                    and post[0] > (subscription.inbox_start_post_id or 0)
                    and post[2] not in own
                ):
                    expected = event_for(subscription, post)
            valid = expected is not None and event == StoredEvent(
                **expected.__dict__, recipient_kind="account", recipient_id=context.account.pk
            )
            outcomes[event.event_id] = Evaluation("visible" if valid else "invalid")
        return outcomes

    def render(self, events, context):
        """Show only current public board names or generic Boards navigation."""
        if any(outcome.status != "visible" for outcome in self.evaluate(events, context).values()):
            raise ValueError("Board activity changed before presentation")
        if len(events) > 1:
            return RenderedNotice("New activity on your subscribed boards.", (_board_action(),))
        [event] = events
        board_id = event.payload["board"]
        name = Board.objects.values_list("name", flat=True).get(pk=board_id)
        return RenderedNotice(f"New activity on {name}", (_board_action(board_id),))


def _board_action(board_id=None):
    if board_id is None:
        return NoticeAction("Browse boards", command="+bb")
    return NoticeAction(
        "Read board",
        command="+bb",
        route_name="evennia_boards:board-detail",
        route_args=(board_id,),
    )
