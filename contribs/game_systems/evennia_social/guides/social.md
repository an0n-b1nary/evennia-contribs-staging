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

Some players would rather not be findable from across the game. `+unfindable on` leaves your character out of `+where`, the hangout counts, and any map of who's where. You still show in `who`, and anyone in the same room sees you as usual. Staff can still see where you are. `+unfindable off` undoes it. The setting is per character.

`+where/ic` and `+where/ooc` narrow the list to in-character or out-of-character rooms.

## Moving to each other

`+join` and `+summon` only send a request. Nobody moves until the other person accepts it with `+join/accept` or `+summon/accept`, and they're free to decline. `+join/pending` and `+summon/pending` show requests waiting on you.

Accepting works even in a room closed to teleporting, because accepting is the consent that counts. It doesn't get anyone into a home or other place they aren't allowed to enter, though.

:::insight[Nobody is moved without saying yes]
A request is all you can send. Whoever would be moved, or would receive a visitor, gets the final say, so nobody can be pulled out of a scene or have one dropped on them.
:::

`+home` takes you to your home room, or to the OOC area if you haven't set one, and `+ooc` takes you straight to the OOC area. `+home/set` makes a room you control your home. `@tel <room>` takes you to a public room you've visited before, or one you control. Your game may open more rooms to it.

## Pages

A page can go to several people at once: `page <name>,<name>=<message>`. `page/last` shows the pages you've received, and `page/recall` shows those you've sent as well. Pages belong to the character, so they never reveal your other characters.

## Profiles

`+finger` shows a character's profile: identity fields such as pronouns and role, a quote, roleplay preferences, a short bio (`+finger/edit`), and a few fields of your own (`+finger/custom`). `+finger/follow <theme>` lists themes you'd like to play, so others can find you through them, and `+finger/public <theme>` chooses whether others see each one.

## Ignoring someone

`+ignore <character>` hides that player's poses behind a short placeholder, drops their whispers and blocks their pages. It applies to every character that player has, not only the one you named. `+ignore/remove` undoes it. Messages from staff always get through.

## Rooms

`+mood` shows a short line under a room's description about how it feels right now: "Crowded and loud", say. The room's owner and staff can set it, and so can participants in a public scene running there. In a private scene, only the person who started it can.

A room's owner can also add a lasting smell or sound with `+roomconfig/smell` and `+roomconfig/sound`, and mark the room as a hangout with `+roomconfig/hangout <type>`. `+roomconfig/unhangout` removes that designation.

## Visiting as a guest

Guests can page staff but not other players. `+ooc` and `+home` take a guest back to their own lounge, and guests are marked as guests when others list who's connected.
