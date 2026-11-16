# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""Serialize Lore decisions and allocate stable source transition identities."""

import hashlib
import inspect
import json
from functools import wraps

from django.db import transaction
from django.db.models import F


def decision_operation(kind, actor_argument):
    """Lock only the source row, refreshing stale callers before any mutation."""

    def decorate(method):
        signature = inspect.signature(method)

        @wraps(method)
        def execute(self, *args, **kwargs):
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            actor = bound.arguments[actor_argument]
            from evennia.accounts.models import AccountDB
            from evennia.objects.models import ObjectDB

            if actor is not None and (not isinstance(actor, AccountDB | ObjectDB) or not actor.pk):
                raise ValueError("Lore decision actor must be a saved account or character")
            with transaction.atomic():
                type(self).all_objects.filter(pk=self.pk).update(
                    notice_sequence=F("notice_sequence")
                )
                live = type(self).all_objects.select_for_update().get(pk=self.pk)
                for field in self._meta.concrete_fields:
                    setattr(self, field.attname, getattr(live, field.attname))
                self._state.fields_cache.clear()
                data = [
                    kind,
                    self.layer_digest,
                    ["account" if isinstance(actor, AccountDB) else "character", actor.pk]
                    if actor is not None
                    else None,
                    (bound.arguments.get("note") or "").strip()[:500],
                    self.author_id,
                ]
                fingerprint = hashlib.sha256(json.dumps(data).encode()).hexdigest()
                same = (
                    kind != "unsealed"
                    and self.affirmation == kind
                    and self.notice_fingerprint == fingerprint
                )
                if not same:
                    self.notice_sequence += 1
                    self.notice_fingerprint = fingerprint
                    self.save(update_fields=["notice_sequence", "notice_fingerprint"])
                self._notice_duplicate = same
                try:
                    return method(self, *args, **kwargs)
                finally:
                    self.__dict__.pop("_notice_duplicate", None)

        return execute

    return decorate
