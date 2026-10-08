# evennia-rp-equipment

> **Preview (0.1.0, Pre-Alpha).** This package was written directly as a
> contrib, and its API may move while the rest of the rp- cluster is built on
> it. Pin an exact commit.

Wearable gear for RP-focused [Evennia](https://www.evennia.com) games, built on
[`evennia-rp-chargen`](../evennia_rp_chargen/README.md). It provides:

- **plain items anyone can make**, each with a description, a *worn line* that
  appears in the wearer's description, and a slot;
- **requirements** that tie wearing an item to the wearer's build: `+` pips or
  weakness on a stat, an equipped ability, or a held flaw;
- **a guard on worn gear:** while an item is worn, the build changes it
  depends on are refused, for players and staff alike;
- **wearing that freezes with the build lock,** so gear can't change mid-scene
  any more than pips or loadout can;
- an **audit** for worn gear whose requirements a ruleset or catalog edit has
  broken.

**Equipment grants nothing.** It has no stat modifiers and adds nothing to
checks. Its only mechanical effect is to *constrain*: an item asks its wearer
to commit part of a build they already have. Anyone can describe their
character holding a sword without this package. Gear is for players who want
that commitment, and who want it shown in their description.

It requires `evennia-rp-rules` and `evennia-rp-chargen` (0.3 or later, for the
change guard). It needs no combat system. See
[`example_game`](../../../example_game/README.md) for the wired reference
integration.

---

## Concepts

**Items.** `+gear/make` creates an item of `RP_EQUIPMENT_TYPECLASS` in the
maker's hands. Its prose is the ordinary `desc`, plus a `worn_line` such as "a
cloak of deep indigo", shown in the wearer's description while it's worn. When
there's no worn line, the item's name is shown. Each character may have up to
`RP_EQUIPMENT_ITEM_CAP` items of their making in the world at once.

**Slots** are flavour. `RP_EQUIPMENT_SLOTS` only sets the order worn lines are
shown in (unlisted slots come last). Any number of items can share a slot.

**Requirements.**

| Text | Kind | Met when |
|---|---|---|
| `Strength +2` or `Strength ++` | pips | the stat carries at least 2 `+` pips |
| `Resolve -1` or `Resolve -` | weakness | the stat carries at least 1 weakness |
| `ability Proficiency: Blades` | ability | that ability (for that tag) is equipped |
| `flaw Reckless` | flaw | that flaw is held |

Requirements are stored by stat, ability and tag *key*, so renaming them in the
ruleset or catalog doesn't orphan anything. A requirement nobody could meet
(more pips than the stat can carry) is refused when it's set.

- **Wearing** needs every requirement met. There's one exception: an ability
  the wearer doesn't own only marks the item "not fully attuned", with no
  mechanical effect. An ability they own but haven't equipped must be
  equipped first.
- **While worn,** chargen's change guard refuses any build change that would
  turn a met requirement unmet: moving the pips off the stat, unequipping or
  revoking the ability, shedding the flaw. The refusal names the item:
  *"Strength ++ is held by your Cursed Axe. Take that off first."*
- **There's no staff override.** Staff tools are refused the same way, so a
  build and the gear that depends on it never disagree; staff take the item off
  first, as a player would. Gaining things never conflicts with gear, so
  acquiring, equipping, upgrading and granting are never refused.
- **The lock.** Wearing and removing are refused whenever
  `evennia_rp_chargen.locks.frozen()` is true: any lock scope locked on a
  finalized sheet.

**Who can change an item.** Only its maker, and only until a character other
than the maker has held it. From then on the item is *sealed*: its prose, slot
and requirements are fixed. An owner who doesn't like an item's requirements
can simply not wear it. Requirements can't change while the item is worn, and
only the holder can destroy an item, once it's taken off.

**Staying put.** A worn item refuses `get`, `drop` and `give`, telling the
player to remove it first; code that moves it with those move types is refused
as well. A staff teleport still moves it, and takes it off.

**The audit.** Two things change the rules rather than a character, and so go
around the guard: editing the ruleset or catalog, and writing a sheet without
chargen's services. `audit.problems()` lists worn gear whose requirements are
now unmet or name something the game no longer has. It never changes anything;
staff settle each case by hand.

---

## Quick start

Install `evennia-links`, `evennia-rp-rules` and `evennia-rp-chargen` first,
then this package. Add the app after chargen:

```python
# server/conf/settings.py
INSTALLED_APPS += [
    "evennia_rp_rules",
    "evennia_rp_chargen",
    "evennia_rp_equipment",
]
RP_EQUIPMENT_SLOTS = ("head", "body", "hands", "feet", "weapon", "accessory")
```

There are no models and no migrations. The guard connects itself in `ready()`.

Show worn gear in characters' descriptions:

```python
# typeclasses/characters.py
from evennia_rp_equipment.typeclasses import EquipmentCharacterMixin

class Character(EquipmentCharacterMixin, ObjectParent, DefaultCharacter):
    ...
```

Put the mixin before the classes it extends. It overrides `get_display_desc`
(to add the worn lines) and `filter_visible` (to leave worn items out of "You
see"), and calls `super()` for both. A game that installs equipment as an
optional partner can't import the mixin unconditionally. It calls
`display.with_worn()` and `display.hide_worn()` from its own overrides instead,
gated on `apps.is_installed("evennia_rp_equipment")`.

Add the commands, and optionally log the audit at startup:

```python
# commands/default_cmdsets.py
from evennia_rp_equipment.commands import EquipmentCmdSet
self.add(EquipmentCmdSet)

# server/conf/at_server_startstop.py, in at_server_start()
from evennia_rp_equipment.audit import log_problems
log_problems()
```

To use your own item typeclass (for an `ObjectParent` mixin, say), subclass
`EquipmentMixin` and point `RP_EQUIPMENT_TYPECLASS` at it:

```python
class Gear(EquipmentMixin, ObjectParent, DefaultObject):
    pass
```

---

## Commands

| Command | Who | Does |
|---|---|---|
| `+gear` | anyone | The equipment you carry, with slots and what's worn |
| `+gear/make <name>[=<slot>]` | anyone | Make a plain item |
| `+gear/desc`, `/line`, `/slot <item>=<text>` | maker | Describe it, set its worn line, set its slot |
| `+gear/require <item>=<requirement>`, `/unrequire <item>=<n>` | maker | Add or remove a requirement |
| `+gear/info <item>` | anyone | Prose, maker, and each requirement's status for you |
| `+gear/destroy <item>` | holder | Destroy an item you carry and aren't wearing |
| `+gear/audit` | staff | Worn gear whose requirements no longer hold |
| `+wear <item>`, `+remove <item>` | wearer | Put on or take off; announced to the room |
| `+worn [<character>]` | anyone | What you, or someone here, is wearing |

---

## API

```python
from evennia_rp_equipment import services
from evennia_rp_equipment.services import GearError

item = services.make(char, "Cursed Axe", slot="weapon")
services.set_worn_line(char, item, "a cursed axe of black iron")
services.add_requirement(char, item, "Strength +2")   # returns the Requirement
notices = services.wear(char, item)                   # "not fully attuned" notices
services.remove(char, item)
services.report(char, item)                           # [(Requirement, status), ...]
```

Every service raises `GearError` with a message fit to show the player.
`requirements.parse()`, `describe()` and `status()` work on single requirements.
The statuses are `MET`, `UNMET`, `UNATTUNED` and `UNKNOWN`.
`display.worn_items(char)` lists what a character wears, in slot order.
`audit.problems()` returns the audit's lines, and `audit.log_problems()` also
logs them.

---

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `RP_EQUIPMENT_TYPECLASS` | `"evennia_rp_equipment.typeclasses.Equipment"` | What `+gear/make` creates |
| `RP_EQUIPMENT_SLOTS` | `("head", "body", "hands", "feet", "weapon", "accessory")` | Order of worn lines; slots are flavour |
| `RP_EQUIPMENT_ITEM_CAP` | `20` | Items of one character's making in the world at once (`None`: no cap) |
| `RP_EQUIPMENT_STAFF_LOCK` | `"cmd:perm(Builder)"` | Who may run `+gear/audit` |

Requirement wording uses chargen's ruleset and catalog names. The lock refusal
is chargen's own `locks.locked_message()`.

---

## Roadmap

Linking items to lore entries is planned for a later minor version. A crafting
contrib will decorate these same items (hallmarks, layered descriptions,
auras) rather than define its own; trading between characters belongs to an
economy contrib.
