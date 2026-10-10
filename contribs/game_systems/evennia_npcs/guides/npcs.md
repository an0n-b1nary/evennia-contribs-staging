---
title: Playing NPCs
key: npcs
category: Roleplaying
requires: NPCS_REVEALED
summary: Create, share and portray supporting characters.
---

# Playing NPCs

NPCs let you bring supporting characters into a scene while keeping their
identity and appearances together. A template represents a kind of person;
a unique NPC represents one recurring character.

Use `+npc` to browse, `+npc/create Name=unique` to create an identity, and
`+npc/desc Name=Description` to describe it. Its owner can share play access
with `+npc/permit Name=Character`. Ask an owner through `+npc/request Name=Reason`.

`+npc/spawn Name` places an instance in your room and prints its object number.
`+npc/puppet #number` starts virtual portrayal. You stay on your character while
pose, say, emit, semipose and tests use the NPC. Everyone sees who is playing it.
`+npc/unpuppet` returns to your normal voice; `+npc/despawn #number` removes the
instance and preserves its history.

A unique NPC can appear only once at a time. Someone already portraying an
instance must release it before another player takes over. Moving away or
losing permission ends virtual portrayal. Private scenes still require an
invitation for your own character.

`+npc/history Name` shows appearances you are currently allowed to read.
`+npc/plot Name=#thread` associates an NPC with an accessible plot thread.
NPC play grants no extra RP rewards and needs no combat system.
