# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""
The two layers of a lore entry, and the rules that keep them honest.

An entry's ``body`` is its **IC content**: what characters know, read and
repeat. It may be false, because rumors and legends can be. Its **OOC layer**
is what players know about it: the ``accuracy`` field and the ``ooc_notes``.
The OOC layer is never false. It can say plainly that the IC story is wrong.

Kinds say how the world treats the content. They are a settings vocabulary
with stable keys, so a game can define its own::

    LORE_KINDS = {"fact": "Fact", "rumor": "Rumor", "legend": "Legend"}
    LORE_ACCURATE_KINDS = ("fact",)   # kinds whose content is always accurate
    LORE_DEFAULT_KIND = "fact"

Accuracy is fixed: ``accurate``, ``inaccurate``, ``partly`` or ``open``.

Rules (``validate``):

- an always-accurate kind (a Fact) must be ``accurate``;
- ``inaccurate`` and ``partly`` need OOC notes saying what is true;
- sealed notes need ``open`` accuracy, so players see "not settled", which is
  true for them.

Nothing here imports models, so it is safe at app-load time and from forms.
"""

import hashlib
import json

from django.conf import settings

DEFAULT_KINDS = {"fact": "Fact", "rumor": "Rumor", "legend": "Legend"}
DEFAULT_ACCURATE_KINDS = ("fact",)

ACCURATE = "accurate"
INACCURATE = "inaccurate"
PARTLY = "partly"
OPEN = "open"

ACCURACY_CHOICES = (
    (ACCURATE, "Accurate"),
    (INACCURATE, "Inaccurate"),
    (PARTLY, "Partly accurate"),
    (OPEN, "Open"),
)
ACCURACY_LABELS = dict(ACCURACY_CHOICES)

#: Accuracies whose OOC notes must say what is actually true.
NEEDS_NOTES = (INACCURATE, PARTLY)


class LoreLayerError(ValueError):
    """An entry's kind, accuracy and notes would break a layer rule."""


def kinds():
    """Return the game's kinds as an ordered ``{key: label}`` dict."""
    configured = getattr(settings, "LORE_KINDS", None)
    return dict(configured) if configured else dict(DEFAULT_KINDS)


def accurate_kinds():
    """Return the kind keys whose content is always accurate."""
    return tuple(getattr(settings, "LORE_ACCURATE_KINDS", DEFAULT_ACCURATE_KINDS))


def default_kind():
    """Return the kind given to new entries that don't name one."""
    configured = getattr(settings, "LORE_DEFAULT_KIND", None)
    return configured or next(iter(kinds()))


def default_accuracy(kind):
    """Return a new entry's accuracy: accurate for a Fact, open for anything else.

    Open means "not yet decided", which is true of a rumor nobody has
    settled. Defaulting a rumor to accurate would have the OOC layer claim
    something its author never said.
    """
    return ACCURATE if kind in accurate_kinds() else OPEN


def kind_label(key):
    """Return a kind's label; a kind a game has since removed shows its key."""
    return kinds().get(key) or str(key).replace("_", " ").title()


def accuracy_label(key):
    """Return an accuracy's label."""
    return ACCURACY_LABELS.get(key, str(key).title())


def match_kind(text):
    """Return the kind key matching *text* (key or label, any case), or None."""
    wanted = (text or "").strip().lower()
    for key, label in kinds().items():
        if wanted in (key.lower(), label.lower()):
            return key
    return None


def match_accuracy(text):
    """Return the accuracy key matching *text* (key or label, any case), or None."""
    wanted = (text or "").strip().lower()
    if wanted == "partly accurate":
        return PARTLY
    return wanted if wanted in ACCURACY_LABELS else None


def validate(kind, accuracy, ooc_notes="", sealed_notes="", *, check_kind=True):
    """Raise LoreLayerError if this combination breaks a layer rule.

    Args:
        kind (str): Kind key.
        accuracy (str): Accuracy key.
        ooc_notes (str): The public OOC notes.
        sealed_notes (str): Staff-only notes awaiting unsealing.
        check_kind (bool): False skips the "is this kind configured" test, so
            an entry keeps a kind a game later removed until someone changes it.
    """
    if check_kind and kind not in kinds():
        names = ", ".join(kinds().values())
        raise LoreLayerError(f"Unknown kind '{kind}'. Choose from: {names}.")
    if accuracy not in ACCURACY_LABELS:
        names = ", ".join(key for key, _ in ACCURACY_CHOICES)
        raise LoreLayerError(f"Unknown accuracy '{accuracy}'. Choose from: {names}.")
    if kind in accurate_kinds() and accuracy != ACCURATE:
        raise LoreLayerError(
            f"A {kind_label(kind)} is always accurate. "
            "Choose another kind for a claim that may be false or unsettled."
        )
    if accuracy in NEEDS_NOTES and not (ooc_notes or "").strip():
        raise LoreLayerError(
            f"{accuracy_label(accuracy)} lore needs OOC notes saying what's actually true."
        )
    if (sealed_notes or "").strip() and accuracy != OPEN:
        raise LoreLayerError("Accuracy must stay open while notes are sealed.")


def digest(title, summary, body, kind, accuracy, ooc_notes):
    """Fingerprint everything an affirmation vouches for.

    Staff affirm an entry *as described*: its IC content and its OOC layer.
    Affirmation stores this digest; a later edit to any part changes it, and
    the entry then reads "edited since affirmation" until staff look again.
    """
    payload = json.dumps(
        [title or "", summary or "", body or "", kind or "", accuracy or "", ooc_notes or ""],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
