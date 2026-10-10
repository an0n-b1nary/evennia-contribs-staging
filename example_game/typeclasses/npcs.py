"""NPC safeguards precede host Character hooks in the cooperative MRO."""

from evennia_npcs.typeclasses import NPCCharacterMixin

from .characters import Character


class NPC(NPCCharacterMixin, Character):
    pass
