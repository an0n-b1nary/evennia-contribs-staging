---
key: posing
title: Posing and pose order
category: Roleplaying
order: 10
summary: Pose, emit and semipose, whose turn it is, and how poses look to you.
---
A pose is how your character acts in a scene. Everything you pose, emit or say is noted, so the game can keep track of whose turn it is and, if your game runs them, feed scene logs and RP tracking.

- `pose <text>` or `:<text>` puts your name in front: `:leans against the wall.`
- `;<text>` joins your name with no space, for possessives: `;'s eyes narrow.`
- `emit <text>` or `\<text>` sends text as written, with no name added.
- `+pot` shows the pose order.
- `+lastpose` shows everyone's latest pose, and `+lastpose <character>` shows one in full.

## Whose turn it is

`+pot` lists the characters in the room by how long it's been since each posed, longest first. The person at the top has waited the longest, so it's usually their turn. Posing moves you to the bottom.

If you're only watching, `+pot/obs` marks you as observing. `+pot/afk` marks you as away. `+pot/ic` puts you back in the order.

## How poses look to you

These settings change only what you see. Nobody else sees them.

- **Headers:** `+poseheader/on` puts the poser's name above each pose. `+poseheader/format` changes how it looks, and `+poseheader/separator` adds a line between poses.
- **Name highlighting:** `+highlight` colours character names inside poses, yours in one colour and everyone else's in another. `+highlight/self <colour>` and `+highlight/others <colour>` choose them.
