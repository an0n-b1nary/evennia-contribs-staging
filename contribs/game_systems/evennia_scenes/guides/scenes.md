---
key: scenes
title: Scenes and logs
category: Roleplaying
order: 20
summary: Opening a scene, who can pose and read it, and finding logs afterwards.
---
A **scene** is a stretch of roleplay in one room, logged as it happens. Poses, emits and says in the room go into the log while the scene is running, along with OOC chatter, which is kept separate.

Some things that happen in the room are logged too, such as an object being used, credited to whoever caused it. They don't count as anyone's pose.

- `+scene/open <title>` starts a scene in your room, and `+scene` shows the one that's running.
- `+scene/join` and `+scene/leave` add you to the scene or take you out of it. Arriving in the room while a scene is running usually adds you too.
- `+scene/close` pauses the scene, and `+scene/resume <number>` picks it up again.
- `+log` lists your recent scenes, and `+log <number>` reads one.

## Who can pose and who can read

| Privacy | Who can read it on the website | Who can pose |
|---|---|---|
| **Public** | Anyone | Anyone in the room |
| **Pose-private** | Anyone | Only invited characters |
| **View-private** | Only invited characters and staff | Only invited characters |

`+scene/privacy` sets it, and `+scene/invite <character>` invites someone.

Public and pose-private scenes appear on the website while they're running, so people can follow along, and stay there afterwards. There's no separate step to publish a log.

:::insight[Private means private everywhere]
A view-private scene stays off the website for anyone who wasn't invited, and features that point at scenes, such as a map of where play is happening, leave it out too. A privacy setting the game doesn't recognise counts as private, so a scene is never shown by mistake.
:::

## Editing the log

You can fix a typo in your own log entries with `+log/edit <entry>`. Every version is kept, `+log/history <entry>` shows them, and staff can roll back an edit. `+log/ic` and `+log/ooc` show only the IC or OOC entries.

## Scene numbers

Every scene has a number that never changes. Use it with `+scene/resume`, `+scene/info` and `+log`, and to point other people at a scene.

## How it connects

A scene's page on the website lists the lore, plots and calendar events linked to it. Private plots, unpublished lore and cancelled events stay off it. `+scene/title` and `+scene/desc` set the title and description it shows.
