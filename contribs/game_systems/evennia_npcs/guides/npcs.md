---
key: npcs
title: Playing NPCs
category: Roleplaying
requires: NPCS_REVEALED
aliases: [npc]
summary: Creating, sharing and portraying supporting characters.
---
NPCs let you bring supporting characters into a scene: a shopkeeper, a rival, a crowd. Each NPC keeps its description and its history of appearances together, and everyone always sees who is playing it.

- `+npc` lists NPCs, and `+npc <name>` shows one. `+npc/search <text>` finds them.
- `+npc/create <name>=template|unique` creates one, and `+npc/desc <name>=<description>` describes it.
- `+npc/spawn <name>` brings one into your room and tells you its object number.
- `+npc/puppet #<number>` starts playing it, and `+npc/unpuppet` stops.
- `+npc/despawn #<number>` sends it away.

## Templates and unique NPCs

A **template** is a kind of person, such as a city guard, and anyone can play one. Spawn as many as the scene needs. A **unique** NPC is one recurring character. It can appear in only one place at a time, and only its owner and the players they've permitted can play it.

- **Sharing:** `+npc/permit <name>=<character>` lets someone play your NPC, and `+npc/revoke` takes it back. `+npc/transfer` hands ownership to someone else.
- **Asking:** `+npc/request <name>=<reason>` asks an NPC's owner for permission. Owners see requests with `+npc/requests` and answer with `+npc/approve` or `+npc/deny`.
- **Retiring:** `+npc/archive` puts an NPC away, sending any of its spawns away too, and `+npc/restore` brings it back.

An NPC can also have stats and abilities, so it can make tests: `+npc/stat <name>/<stat>=<rating>` changes one stat, and `+npc/abilities <name>=<stable identifiers>` sets the ability list. Each stat edit preserves the others.

## Playing an NPC

While you portray an NPC, your pose, say, emit, semipose and `+test` come from the NPC. You stay on your own character, and the room sees who is playing it. Moving away or losing permission ends the portrayal. If someone is already playing a unique NPC, they release it before anyone else takes over. A spawn nobody has used for a long while may be sent away on its own.

Some games also allow full puppeting, `+npc/fullpuppet`, where you take control of the NPC itself until `+npc/unfullpuppet`.

:::insight[Always attributed]
An NPC never speaks anonymously. Whoever plays it is named, so a supporting character can't be used to say what nobody would put their own name to.
:::

## History and plots

`+npc/history <name>` lists an NPC's appearances, showing only the scenes you're allowed to read. If your game has plots, `+npc/plot <name>=<plot number>` links an NPC to a plot you can see, and `+npc/unplot` removes the link.

## How it connects

Despawning keeps an NPC's history. Playing NPCs earns no extra RP rewards. A private scene still needs an invitation for your own character, whatever NPC you bring.


With Combat and Party installed, ordinary actions, `+combat`, `+party` and
`+bosscheck` follow your current NPC portrayal. Messages identify the NPC
and responsible player. Release portrayal before acting as your own character.
Full puppeting also includes the installed combat and Party cmdsets.
