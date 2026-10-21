---
key: links-staff
title: "Staff: runtime controls"
audience: staff
category: Staff
summary: Reveal switches, freezes, validated runtime overrides and restoring host defaults.
---
## What it's for

Links provides `+runtime` so staff can change explicitly registered controls without a restart. Access uses `LINKS_RUNTIME_STAFF_LOCK`, Builder by default. The owning system decides what each control does.

## Tasks and commands

- **Inspect first:** `+runtime` lists registered names and effective values; `+runtime <NAME>` reads one. Only controls registered by installed systems are available. This command does not edit arbitrary Django settings.
- **Set a value:** `+runtime NAME=<JSON value>` stores a validated override. For example, `+runtime RP_ECONOMY_REVEALED=true` reveals the economy when installed. JSON booleans are lowercase `true` and `false`; text needs double quotes. Invalid names, types or values are refused.
- **What a reveal publishes:** a reveal switch generally makes that system's player commands and its gated guide pages available together. With Guides installed, pages whose `requires:` checks all pass become visible in the index, and links to them become clickable. Turning the switch off hides those pages and turns their links into plain text. Ungated pages remain public; a reveal does not gate every page merely because it ships in that package. Staff-only pages remain staff-only, and guide staff can proofread gated player pages before reveal.
- **Freeze deliberately:** a system's `_FROZEN` control pauses the operations that system guards. It is different from hiding its commands or pages. Read that system's staff guide before using it: cleanup, reading, income and staff exemptions vary by system. A freeze is not a rollback.
- **Reset an override:** `+runtime/reset NAME` removes the database override and returns to the host's configured value, or the registered package default if the host has none. Read the resulting value; reset does not necessarily mean false.

## What's safe to change

Use registered controls and inspect their effects from a player account. Overrides persist across reloads and take precedence over host settings until reset; the operator changing a settings file may otherwise see no effect. Changes record the actor and are logged. Raising or lowering a limit does not rewrite past transactions, and switching a reveal off does not delete existing game data. New or edited guide files still need a reload to be discovered.

## Privacy

A reveal is publication. Check public commands, pages, links and any related web surface before opening a system. Guide staff access follows `GUIDES_STAFF_LOCK`, which a host can configure separately from runtime or individual system locks. Runtime audit logs record who made changes; keep operational details within staff.

## Review jobs

Links runtime controls file no automatic review jobs. Coordinate a reveal or freeze through the host's staff process and record why it was needed. Confirm the player-visible result before marking that task done.
