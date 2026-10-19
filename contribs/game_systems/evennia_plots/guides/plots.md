---
key: plots
title: Plots and arcs
category: The world
order: 20
summary: Starting a plot, running it with threads, tying scenes and events to it, and the bonus for concluding one.
---
A **plot** is a storyline that players run, anything from a feud between two families to a smuggling ring. A plot ties together the scenes, events and posts that tell its story, so anyone can follow it from start to finish. Staff group plots into larger [[glossary-arc|arcs]].

- `+plot` lists active public plots, and `+plot <number>` shows one.
- `+plot/create <name>=<tagline>` proposes a plot, and `+plot/activate <number>` starts it.
- `+plot/update <number>` adds an in-character update to the plot's story, and `+plot/update/ooc` adds an OOC note that only the plot's participants and staff can read.
- `+plot/link/scene <number>=<scene>` ties a scene to the plot. `/link/event` and `/link/post` do the same for calendar events and board posts.
- `+plot/conclude <number>` ends it.

## Owners

Whoever starts a plot is its first **owner**. Owners run the plot: its tagline, privacy, invitations and threads. `+plot/owner <number>=<name>` adds another owner, so a plot can be run by a group. Owning a plot doesn't earn anything by itself.

## Threads

A [[glossary-thread|thread]] is an open question, problem or lead inside a plot: "Investigate the drowned bell", "Venture to the salt flats", "Why do the wells run red?". Threads are numbered within their plot, so the third thread of plot 12 is `#12.3`.

- `+plot/thread <number>=<title>` adds a thread.
- `+plot/thread/lead #12.3` says you're chasing it, and `/thread/interest` marks your interest. Neither gives you any special powers. They show who's working on what.
- `+plot/thread/resolve #12.3=<what happened>` closes it with a short summary.

Each plot's owners decide who may add threads:

| Setting | Who adds threads |
|---|---|
| **Open** | Anyone who can link things to the plot |
| **By request** | Anyone may ask; the owners accept or decline |
| **Owners only** | The owners |

`+plot/threads <number>=<open|request|owners>` changes it. Under **By request**, `+plot/thread` sends your thread to the owners instead, and `+plot/thread/withdraw` takes the request back if you change your mind.

### Held threads

Owners can mark a thread **[[glossary-held|held]]**: they already know the answer, and play is heading towards it. A plot with an open held thread shows **Owner-led**, so you can tell at a glance that someone is steering it, rather than it being left open to wherever players take it.

Owners can also write the answer down as a **sealed answer**. Only the owners and staff can read it. When the thread resolves, the owners can reveal it, along with every earlier wording, which shows the answer was decided in advance. They can also keep it sealed, if the answer should stay a secret in the story.

### Loose ends

When a plot ends, any threads still open become **loose ends**. That's fine: not every question needs an answer. If the story carries on in a sequel plot, its owners can pick a loose end up there with `+plot/thread/carry`.

:::insight[Threads are a tool, not a scoreboard]
Threads never earn or cost anything. A plot isn't worth more for having many threads, or for resolving them all. They're there to help people run a story together.
:::

## Privacy

| Privacy | Who can read it | Who can link things to it |
|---|---|---|
| **Public** | Anyone | Anyone, while it's active |
| **Invite-only** | Anyone | Its owners, invited characters and staff |
| **Private** | Its owners and staff | Its owners and staff |

`+plot/privacy` sets it, and `+plot/invite` invites someone.

## Related plots

Owners can mark their plot as a sequel to an earlier one with `+plot/sequel <number>=<earlier>`. `+plot/relate <number>=<other>` proposes a link to another plot, and it shows once that plot's owners accept it with `+plot/relate/accept`, so nobody's story is tied to yours without their say.

## Concluding a plot

When a plot concludes, everyone who took part gets a small XP bonus, if your game uses XP. The bonus grows with how the story was run:

- **Scheduling ahead** counts the most: an event on the calendar, linked to the plot, with good notice.
- **More than one scene** linked to the plot adds a little.
- **An in-character board post** linked to it adds a little more.

A plot concluded very soon after it was started earns no bonus.

Only a plot's owners and staff can conclude it. If a plot has stalled and its owners have moved on, `+plot/request-conclude <number>` asks staff to conclude or archive it, when your game takes requests to staff.

:::insight[Rewarding the habits that include people]
The bonus doesn't reward winning, or even finishing quickly. It rewards things that let other people join in: notice, more than one session, and a written account anyone can read.
:::

## Arcs

Staff group plots into **arcs**, the larger stories of the game. One arc at a time can be the **current** arc. Some arcs are **downtime** arcs, a breather between stories, and your game may pay less XP or none while one is current. Play carries on as usual during downtime.
