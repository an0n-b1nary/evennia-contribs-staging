---
key: regions-staff
title: "Staff: regions"
audience: staff
category: Staff
summary: Region descriptions, room membership, primary regions and private places.
---
## What it's for

Staff name geographic areas and maintain which rooms belong to them. See [[regions]] for discovery. Creation, editing and membership commands use `REGIONS_STAFF_LOCK`, Builder by default. Website staff access follows the shared Links web policy separately.

## Tasks and commands

- **Create and describe:** `+region/create <name>=<description>` creates an area. `+region/edit <name>` opens its description for editing; `/view <name>` lists its details and rooms.
- **Membership:** `+region/add-room <name>=<#room>` adds a room; `/here-add <name>` uses your current room. `/remove-room <name>=<#room>` removes that membership. One room may belong to several regions.
- **Choosing the primary region:** `+region/primary <name>[=<#room>]` selects one of the room's existing memberships, using the current room when omitted. The first membership becomes primary automatically. Removing a primary membership promotes the earliest remaining one.
- **Check the result:** `+region/here` shows the current room's memberships. Check integrations that use its primary region, such as environment inheritance or build policy, before changing it on a live anchor.

## What's safe to change

Descriptions and membership are intended staff edits. Use commands for primary changes so a room does not acquire two primaries. Preserve region IDs used by other systems instead of deleting and recreating an area merely to rename it. Changing a primary region can affect future decisions in partner systems; it does not move a room or redraw its exits.

## Privacy

Region membership does not make a private room public. The website and API apply the host's room-visibility policy; a failed configured visibility check hides the room. Staff should verify the ordinary player's list after changing membership, especially around homes and unpublished places.

## Review jobs

Regions files no automatic review jobs. Work corrections from the game's request tools, check the affected rooms and memberships, then reply with the change made.
