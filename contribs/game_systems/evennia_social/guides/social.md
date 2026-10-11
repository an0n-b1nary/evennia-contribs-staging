---
key: social
title: Finding people and getting together
category: Roleplaying
order: 30
summary: Where people are, profiles, pages, ignoring someone, and moving to each other by consent.
---
These commands help you find people to play with, talk to them out of character, and get to the same place.

- `+where` shows who's connected and where they are. `+hangouts` lists [[glossary-hangout|hangouts]], busiest first.
- `+finger <character>` shows someone's profile, and `+finger/set` fills in yours.
- `page <character>=<message>` sends a private OOC message, and `page <message>` replies to the last person who paged you.
- `+join <character>` asks to go to someone, and `+summon <character>` asks them to come to you.
- `ooc <message>` speaks out of character to the room.

## Being found

Some players would rather not be findable from across the game. `+unfindable on` leaves your character out of `+where`, and off any map of who's where. You still show in `who`, and anyone in the same room sees you as usual. `+unfindable off` undoes it. The setting is per character.

## Moving to each other

`+join` and `+summon` only send a request. Nobody moves until the other person accepts it with `+join/accept` or `+summon/accept`, and they're free to decline. Accepting works even if the destination is a private room, because accepting is the consent that counts.

:::insight[Nobody is moved without saying yes]
A request is all you can send. Whoever would be moved, or would receive a visitor, gets the final say, so nobody can be pulled out of a scene or have one dropped on them.
:::

`+home` takes you to your home room, or to the OOC area if you haven't set one, and `+ooc` takes you straight to the OOC area.

## Profiles

`+finger` shows a character's profile: identity fields such as pronouns and role, a quote, roleplay preferences, a short bio (`+finger/edit`), and up to ten fields of your own. `+finger/follow <theme>` lists themes you'd like to play, so others can find you through them.

## Ignoring someone

`+ignore <character>` hides that player's poses behind a short placeholder, drops their whispers and blocks their pages. It applies to every character that player has, not only the one you named. `+ignore/remove` undoes it. Messages from staff always get through.

## Room mood

`+mood` shows a short line under a room's description about how it feels right now: "Crowded and loud", say. The room's owner and staff can set it, and so can participants in a public scene running there. In a private scene, only the person who started it can.
