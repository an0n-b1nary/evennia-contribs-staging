# Changelog

## [0.2.0] - 2026-10-22

### Breaking

- Replace bulk stats with `+npc/stat name/stat=rating` and JSON combat profiles with `+npc/profile name/field=value`. Mapping entries use qualified fields such as `action_weights.standard`; lists use comma-separated like items. Empty values clear lists or mappings and remove mapping entries. Single-field edits preserve other fields under the blueprint lock. Unknown, ambiguous and stacked switches are refused; unique switch prefixes work. Combat actor resolution and puppet feedback prefixes will ship with the combat command changes.

## 0.1.4 — 2026-10-20

- Add the staff-only `npcs-staff` guide: tasks and command permissions, safe changes, privacy and review queues. Package it for discovery by evennia-guides.

## 0.1.3 — 2026-10-18

- Refreshed the `npcs` guide page: templates and unique NPCs, sharing and
  requests, archiving, full puppeting where a game allows it, and plot links.
- `+npc/plot` help says "plot" where it still said "thread".

## 0.1.2 — 2026-10-13

- Apply shared communication restrictions to NPC portrayal and fallback room
  commands, keeping IC portrayal open while stopping OOC-room mute bypasses.

## 0.1.1 — 2026-10-11

- Say "plot" where messages and the guide said "plot thread" (`+npc/plot Name=#plot`), following evennia-plots 0.7, where a thread is now a question inside a plot.

## 0.1.0 — 2026-10-10

- Add templates, unique identities, sharing, permission requests, ownership transfer and archiving.
- Add attributed virtual portrayal, opt-in full puppeting, NPC stat sources and optional contest commands.
- Preserve scene appearances after despawn; own optional plot links and their creative-content contribution.
- Add reload-safe rollout switches, idle cleanup and durable, separately gated combat profiles.
- Wire a populated reference sandbox and partner-absence validation.
