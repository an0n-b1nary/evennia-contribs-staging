# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""An NPC mixin for host characters, plus a standalone default typeclass."""

from evennia.objects.objects import DefaultCharacter


class NPCCharacterMixin:
    """Place before the host Character so NPC safeguards take precedence."""

    def at_object_creation(self):
        super().at_object_creation()
        self.tags.add("npc", category="npc_system")
        self.locks.add("puppet:false();get:false()")
        self.cmdset.add_default("evennia_npcs.commands.NPCFullCmdSet", persistent=True)

    def get_display_name(self, looker=None, **kwargs):
        from .services import attribution

        return attribution(self)

    def get_rp_actor_name(self):
        """An auditable identity for contest records and their narration."""
        from .services import attribution

        return attribution(self)

    def access(self, accessing_obj, access_type="read", default=False, **kwargs):
        if access_type == "puppet":
            token = self.ndb.npc_puppet_token
            return bool(token and token[0] == accessing_obj.pk)
        return super().access(accessing_obj, access_type=access_type, default=default, **kwargs)

    def get_rating(self, stat_key):
        from evennia_rp_rules.subjects import DictStatSource

        from .services import record_for

        record = record_for(self)
        if record:
            return DictStatSource(record.blueprint.stat_block).get_rating(stat_key)
        return None

    def get_modifiers(self, check):
        # Host-specific abilities may supply a provider via rp-rules. They
        # are durable identities, not assumed PC catalog rows or free bonuses.
        return []

    def msg(self, text=None, from_obj=None, **kwargs):
        actor = self.ndb.npc_feedback_actor
        if actor is not None and actor != self and not self.account and from_obj is None:
            return actor.msg(text, **kwargs)
        return super().msg(text, from_obj=from_obj, **kwargs)

    def at_pre_puppet(self, account, session=None, **kwargs):
        from .services import NPCError, consume_full_puppet_token

        if not consume_full_puppet_token(self, account, session):
            raise NPCError("Use +npc/fullpuppet with an authorized character to play this NPC.")
        return super().at_pre_puppet(account, session=session, **kwargs)

    def at_post_puppet(self, **kwargs):
        # Do not run host PC login rewards, stipends or summaries for an NPC.
        return DefaultCharacter.at_post_puppet(self, **kwargs)

    def at_post_unpuppet(self, account=None, session=None, **kwargs):
        from .services import record_for, release_npc

        record = record_for(self)
        if account and account.db._last_puppet == self:
            account.db._last_puppet = record.controller if record else None
        release_npc(self)
        # A spawned NPC stays on the grid when its player returns to a PC.
        # DefaultCharacter would stash it off-grid like a logged-out player.

    def at_object_delete(self):
        from .services import _release, record_for

        allowed = super().at_object_delete()
        if allowed:
            record = record_for(self)
            if record:
                _release(record)
        return allowed


class NPCCharacter(NPCCharacterMixin, DefaultCharacter):
    pass
