---
key: lore
title: "Lore: facts, rumors and legends"
category: The world
principles: [ic-may-mislead]
summary: How lore entries work, how characters learn them, what the OOC notes promise, and what staff affirmation means.
---
Lore is the world's shared memory, and players write most of it. Anyone can write an entry, and characters pick entries up as they play, from each other, and from books.

- `+lore` browses published entries, and `+lore/read <id>` reads one.
- `+lore/submit <title>` writes a new entry in the editor.
- `+lore/acquired` lists the entries your character knows.
- `+share <id>=<character>` passes an entry you know to someone else.
- `+investigate` shows what your character is looking into, and its switches change it.

Your game may have staff approve new entries before they're published. If so, `+lore/submit` sends yours to their queue.

## Two layers

Every entry has two parts.

- **In character** is what characters know, read and repeat. It can be wrong. A rumor can be false, and a legend can be half true.
- **Out of character** is what players know about it: the **accuracy**, and the **OOC notes** that explain where a story came from or what's actually true.

:::insight[The IC layer may mislead; the OOC layer never does]{ic-may-mislead}
Characters can be fooled, and stories are better for it. Players shouldn't be. So the in-character part of an entry may be false, but its OOC notes never are. A character can believe a lie while their player knows exactly what's going on.
:::

## Kinds

| Kind | What it is |
|---|---|
| **Fact** | What is so, as far as anyone in the world can tell. Always accurate. |
| **Rumor** | A claim going around now, about recent or current things. |
| **Legend** | An old story, told everywhere, that nobody living can check. |

Submit with `+lore/submit <title>`, then use `+lore/kind <id>=rumor` to change its kind. Authors can configure their own entries while they await approval. Use `+lore/scene <id>=<scene#>` to link the saved entry to a scene.

## Accuracy

| Accuracy | Meaning |
|---|---|
| Accurate | The IC content is true. |
| Inaccurate | It's false. The OOC notes say what's true. |
| Partly accurate | Some of it is true. The OOC notes say which part. |
| Open | Not decided yet. |

New submissions use the game's default kind and accuracy. Changing the kind preserves its accuracy: after changing a Fact to a Rumor or Legend, use `+lore/accuracy <id>=open` if its truth is undecided. Use `+lore/ooc` when you know more.

## Learning lore

When your game tracks RP, a character may pick up an entry at the end of a session. Entries tied to an active plot, the room or its region are the likeliest. `+investigate/region <name>`, `/tag`, `/entry` or `/plot` tilts what your character picks up towards that topic, and `+investigate/clear` stops.

Characters also learn from each other. `+share` passes on an entry you know, and the other character is told. `+forget` drops an entry from your character's memory, so they can learn it again later.

Some entries are **restricted**: everyone sees their title and a short summary, but only a character who knows the entry can read the rest. `+hint` lists the summaries of restricted lore tied to where you are.

## Books

A book can cite lore entries. Reading a cited page with `read <book>=<page>` teaches your character that entry, if they don't know it already. Looking at a book's contents or a preview teaches nothing. Staff write fixed books called **tomes**, and your game may let crafters cite lore they know in what they make.

:::insight[You learn what you actually read]
Lore comes from reading the page that cites it. Owning the book, skimming its contents or failing to read it teaches nothing, so a character's knowledge follows what they did in the story.
:::

## Affirmation

Affirmation is separate from publishing: an entry doesn't need it to be read, shared or learned. If you'd like staff to confirm an entry, ask with `+lore/affirm`. Everyone can see that you've asked.

When staff affirm an entry, they confirm it's canon **as described**, OOC notes included. For a Fact, that means it's true. For a Rumor, it means people really are saying this, and the accuracy and notes are right.

:::insight[An affirmed rumor can still be false]{ic-may-mislead}
"Affirmed by staff" never makes a rumor's claim true. It means: yes, this rumor is going around, and yes, the OOC notes about it are right.
:::

If staff decline, only you see the decline and their note. Everyone else sees no badge at all. If you edit an affirmed entry, it shows **edited since affirmation** until staff look again. `+lore/history <id>` shows every edit.

## Sealed notes

Some lore holds a mystery the story hasn't solved yet. Staff can keep part of its OOC notes **sealed** until it has. While anything is sealed, the entry's accuracy stays **open**, which is true for everyone who can't see the seal.

When staff unseal the notes, everyone who has the entry is told, either straight away or the next time they log in.

## How it connects

Lore can be linked to scenes, plots, regions and objects: `+lore/scene`, `+lore/plot`, `+lore/region` and `+lore/object`. If your game uses XP, writing a published entry earns some, and so does taking part in a scene that an entry is linked to. `+lore/flag <id>=<reason>` asks staff to look at an entry that seems wrong.

`+lore/plot <entry>=<plot>` links the whole plot (`+plot #N`). Questions inside
it use `+thread #N.T`; those references are not plot IDs.
