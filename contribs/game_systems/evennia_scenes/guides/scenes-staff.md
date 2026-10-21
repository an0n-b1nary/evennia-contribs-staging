---
key: scenes-staff
title: "Staff: scenes and logs"
audience: staff
category: Staff
summary: Managing scenes for others, log versions, rollback and private logs.
---
## What it's for

Staff help a scene's creator manage the record and repair log edits. See [[scenes]] for ordinary use. Staff access uses `SCENES_STAFF_LOCK`, Builder by default.

## Tasks and commands

- **Managing a scene for someone else:** in its room, staff can use `+scene/close`, `/resume [scene number]`, `/title <text>`, `/desc`, `/privacy <public|pose-private|view-private>` and `/invite <character>` where the creator could. `+scene/info <scene number>` inspects a particular scene. Check the scene and room before changing the active one.
- **Restoring a log entry:** `+log/history <entry id>` shows versions and `+log/diff <entry id>=<version>` compares one. `+log/rollback <entry id>=<version>` restores that entry's text as a new recorded revision. It does not roll back the scene or its game mechanics.
- **Editing for someone else:** staff can `+log/edit <entry id>` even when they are not its author. Prefer a correction agreed with the author; the editor remains recorded.

## What's safe to change

Use scene and log commands so edits keep their history. Preserve scene numbers, entry IDs and prior versions. A log rollback changes prose only; it does not reverse XP, tests or combat. Changing a closed scene to public can expose its log immediately on the website.

## Privacy

Pose-private scenes have publicly readable logs; view-private scenes restrict reading and posing to invited characters and staff. Staff can read private logs to support or moderate play. Keep that access within staff, and agree a privacy change with the participants before publishing their scene.

## Review jobs

Scenes files no automatic review jobs. Players may ask through the game's request or report tools. Check the scene, entry and version referenced in the request, make the change through the scene commands, and explain what changed in the reply.
