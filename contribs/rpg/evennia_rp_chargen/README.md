# evennia-rp-chargen

> **Preview (0.2.0, Pre-Alpha).** This package was written directly as a
> contrib rather than extracted from a running game, and its API will move
> while the rest of the rp- cluster is built on it. Pin an exact commit.

Character sheets for RP-focused [Evennia](https://www.evennia.com) games,
built on [`evennia-rp-rules`](../evennia_rp_rules/README.md). It provides:

- graded stats chosen within an **allocation** (point-buy, array, or free);
- **edge** and **weakness** pips under a pip policy;
- a draft → finalized (→ approved) life cycle, with no staff bottleneck by
  default;
- an **ability catalog** of abilities and flaws, with effects stored as data,
  per-tag templates, levels, and a budgeted loadout;
- spending, from a starting allowance first and then from XP;
- **build locks** triggered by IC poses, resolved checks or manual locking,
  released by RP session end, manual unlocking or an idle TTL.

Stat names, rungs and numbers all come from the game's ruleset; this package
ships none of its own.

It requires `evennia-rp-rules` and `evennia-links`; contest is independent.
Earned XP is optional through the ledger seam. See
[MIGRATION_NOTES.md](MIGRATION_NOTES.md) for the contrib-native origin and
upgrade steps, and [`example_game`](../../../example_game/README.md) for the
wired reference integration.

---

## Concepts

**Sheet.** A character's ratings are stored in one Attribute (`rp_stats`) as
rung *keys* and pip counts, never as scores. Retuning the ruleset's numbers
never touches a sheet. A `CharacterBuild` row tracks the sheet's status and
review trail, so staff can query and list sheets.

**Life cycle.**

1. **Draft.** The player picks each stat's rung with `+stats`, within the
   allocation.
2. **Finalized.** The player finalizes once nothing is left to do. After
   that, only staff can change the rungs.
3. **Approved.** With `RP_CHARGEN_REQUIRE_APPROVAL = True`, a finalized sheet
   needs staff approval before it can be used in checks. Without it, which is
   the default, a finalized sheet is playable straight away and staff review
   is optional, after the fact.

**Allocation.** Allocation decides which rungs a draft may have. Allocation
points exist only while the sheet is a draft. They aren't XP, and the sheet
stops showing them once it's finalized.

| Allocation | Params | Rule |
|---|---|---|
| `FreeAllocation` (default) | none | Any rungs |
| `PointBuyAllocation` | `costs`, `budget`, `require_full=False` | Each rung costs points; spend up to the budget |
| `ArrayAllocation` | `array` | Stats take the listed rungs, one each |

A change that breaks the allocation, such as overspending, is refused.
Finalizing is refused until nothing is left to do, such as unset stats or
unused array slots.

**Pips.** Edge (`+`) comes from a budget; weakness (`-`) is free, a
roleplaying choice, and never buys more edge. Both may sit on one stat, and
the resolver uses the net count, while the sheet shows both runs (`B +++ -`).
Pips stay player-managed after finalizing, but not while the build is locked.

**Build locks.** A lock freezes the scopes in `RP_CHARGEN_LOCK_SCOPES`, which
are edge pips and the ability loadout by default.

| From | Event | To |
|---|---|---|
| unlocked | an IC pose, a resolved check, or `+lock` | locked |
| locked | `+unlock`, the RP session ending, or the idle TTL | unlocked |

- **A pose re-locks.** A pose while unlocked locks again, which covers
  "unlock, swap, re-lock".
- **Who is told.** Manual locks and unlocks are announced to the room, so the
  norm is transparency rather than a staff gate. Automatic locks and releases
  are told only to the character.
- **Drafts.** A draft sheet never locks.

**Abilities.** Each catalog entry is an ability or a flaw, and its effects
are evennia-rp-rules effect specs stored as data:

```python
{"key": "domain-expertise", "name": "Domain Expertise", "tag_kind": "domain",
 "acquisition": "xp", "xp_cost": 3, "max_level": 5, "budget_cost": 10,
 "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": 8, "per_level": 1}]}
```

- **Templates.** An entry with `tag_kind` is a template, acquired once per
  tag of that kind. `@tag` in its effects stands for the chosen tag, so one
  entry covers every domain ("Domain Expertise: Performance"), including
  domains staff add later.
- **Equipping.** Equipped copies count against `RP_CHARGEN_LOADOUT_BUDGET`
  and reach checks as modifiers. The loadout is frozen while the build is
  locked.
- **Flaws.** Flaws are free, self-service, always in effect, and give
  nothing back. Staff-only flaws can't be shed by players.
- **One ability model.** There's only one, and it's this one. A combat
  system adds abilities as catalog entries using its own effect kinds
  (`RP_RULES_EFFECT_KINDS`); it doesn't define a second model.

**Spending.** Abilities and their upgrades are paid for from the sheet's
starting allowance first, then from XP through `RP_CHARGEN_XP_LEDGER`.
Without a ledger, the allowance is the limit. Each purchase writes an
`AbilityTransaction` recording how it was funded, so a staff refund returns
exactly what was paid. Upgrade *n* costs `base × factor^(n−1)`
(`RP_CHARGEN_UPGRADE_COST`). The allowance is not XP: it never counts toward
XP totals.

To use earned XP, install `evennia-rp-chargen[xp]`, add `evennia_xp` to
`INSTALLED_APPS`, migrate, and set:

```python
RP_CHARGEN_XP_LEDGER = "evennia_rp_chargen.integrations.xp.EvenniaXPLedger"
```

This adapter checks the app registry before importing XP. Without the partner,
allowance purchases work and purchases needing earned XP report its absence.
With it, allowance, XP, ability copies and audit rows share one database
transaction; a failed purchase rolls them all back.

**Per-tag loadout costs.** A template can set `budget_cost_overrides`, such as
`{"ritual": 15, "performance": 12}`, falling back to `budget_cost` for other
tags. Use tag keys of the template's kind and nonnegative integer costs.
`+abilities/info Domain Expertise: Ritual` shows the resolved cost. Costs
are read from the catalog each time, so rebalancing reaches existing copies.
An over-budget loadout stays equipped and is flagged on the sheet; new equips
are blocked until enough abilities are unequipped. Flaws always cost zero.

**Tags.** The ruleset's tags seed the vocabulary. `TagDefinition` rows add
to it, rename tags, or archive them (`+chargen/tag`, or the admin). Set
`RP_RULES_VOCABULARY = "evennia_rp_chargen.vocabulary.DBVocabulary"` so
checks and commands see the same vocabulary.

---

## Quick start

```bash
pip install evennia-rp-chargen     # pulls in evennia-rp-rules and evennia-links
evennia migrate
```

```python
# server/conf/settings.py
INSTALLED_APPS += ["evennia_rp_rules", "evennia_rp_chargen"]
RP_RULES_RULESET = "world.ruleset"
RP_RULES_SUBJECT_ADAPTER = "evennia_rp_chargen.subject.subject_adapter"

RP_CHARGEN_ALLOCATION = {
    "path": "evennia_rp_chargen.allocation.PointBuyAllocation",
    "params": {"costs": {"d": 0, "c": 1, "b": 2, "a": 4, "s": 7}, "budget": 14},
}
RP_CHARGEN_PIP_BUDGET = 10
RP_CHARGEN_PIP_CAP = 5
RP_RULES_VOCABULARY = "evennia_rp_chargen.vocabulary.DBVocabulary"
RP_CHARGEN_CATALOG_SEED = "world.ruleset.CATALOG"   # a list of catalog entries
RP_CHARGEN_LOADOUT_BUDGET = 100
RP_CHARGEN_STARTING_ALLOWANCE = 10
```

Then seed the vocabulary and catalog. The command is idempotent; add
`--update` to overwrite existing rows from the seed:

```bash
evennia rp_chargen_seed
```

```python
# commands/default_cmdsets.py
from evennia_rp_chargen.commands import ChargenCmdSet

class CharacterCmdSet(default_cmds.CharacterCmdSet):
    def at_cmdset_creation(self):
        super().at_cmdset_creation()
        self.add(ChargenCmdSet)
```

Rename a command by subclassing it: `class CmdEdge(CmdPips): key = "+edge"`.

### Wiring the lock triggers

chargen never connects to a pose signal itself. Call `note_ic_action` from
your game's one pose listener, or from the character's own pose method:

```python
from evennia_rp_chargen.locks import note_ic_action

def on_pose_recorded(sender, character=None, **kwargs):
    note_ic_action(character)
```

The other triggers need no wiring:

- **Checks.** A resolved check (`check_resolved` from evennia-rp-rules) counts
  as IC action.
- **Sessions.** When `evennia-rptracker` is installed, its `rp_session_ended`
  releases the lock.
- **No tracker.** Without the tracker, the lock releases on `+unlock` or after
  `RP_CHARGEN_LOCK_TTL` without IC action. A game with its own tracker calls
  `locks.release(character, locks.SESSION_END)`.

---

## Commands

| Command | Who | Does |
|---|---|---|
| `+sheet [<character>]` | owner; staff for others | The sheet: ratings with both pip runs, edge used, lock state; allocation while drafting |
| `+stats`, `+stats <stat>=<rung>`, `/clear`, `/finalize` | owner | Choose rungs on a draft, then finalize |
| `+pips <stat>=<n>`, `/set`, `/clear`, `/weakness` | owner | Edge and weakness; counts may be numbers or `+++` / `--` |
| `+lock`, `+unlock` | owner | Lock or unlock edge and loadout, announced |
| `+abilities`, `/list`, `/info`, `/equip`, `/unequip`, `/flaw`, `/unflaw` | owner | Your abilities and flaws, the catalog, and the loadout |
| `+spend`, `+spend/ability <ability>[: <tag>]` | owner | Your allowance and XP; buy an ability |
| `+upgrade <ability>[: <tag>]` | owner | Raise an ability a level |
| `+chargen`, `/list`, `/approve`, `/reopen`, `/setstat` | staff | List, view, approve and reopen sheets, and set any rating directly |
| `+chargen/grant`, `/revoke[/refund]`, `/allowance`, `/tag` | staff | Give, set the level of, or take away abilities; set allowances; add tags |

`/setstat` bypasses allocation and pip limits, and reports anything it breaks.
Nobody but the owner and staff can see a sheet, and it never shows scores.

---

## API

```python
from evennia_rp_chargen import services, locks
from evennia_rp_chargen.services import ChargenError

services.set_stat(char, "charisma", "B")       # draft only, within the allocation
services.set_edge(char, "charisma", 3)         # within the pip policy, unless locked
services.set_weakness(char, "will", 1)
services.finalize(char)                        # ChargenError lists what's left
services.approve(char, by=staff)               # and services.reopen(char, by=staff)

locks.note_ic_action(char); locks.lock(char); locks.unlock(char)
locks.release(char, locks.SESSION_END)
```

Every service raises `ChargenError` with a message fit to show the player.
`StatHandler(char)` reads and writes ratings without policy. `ChargenSubject`
and `subject_adapter` expose a playable sheet to checks. A draft sheet raises
a `CheckError` that tells the player to finish it.

---

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `RP_CHARGEN_STAFF_LOCK` | `"cmd:perm(Builder)"` | Staff commands and viewing others' sheets |
| `RP_CHARGEN_ALLOCATION` | free | `{"path": ..., "params": {...}}` |
| `RP_CHARGEN_ALLOCATION_NOUN` | `"build points"` | What allocation points are called |
| `RP_CHARGEN_PIP_BUDGET` | `None` | Total edge per character (`None`: no budget) |
| `RP_CHARGEN_PIP_CAP` | `None` | Most edge on one stat (`None`: the scale's maximum) |
| `RP_CHARGEN_WEAKNESS_CAP` | `None` | Most weakness on one stat (`None`: the scale's maximum) |
| `RP_CHARGEN_PIP_NOUN`, `RP_CHARGEN_WEAKNESS_NOUN`, `RP_CHARGEN_LOADOUT_NOUN` | `"edge"`, `"weakness"`, `"loadout"` | Player-facing nouns |
| `RP_CHARGEN_LOCK_SCOPES` | `("pips", "loadout")` | What a lock freezes |
| `RP_CHARGEN_LOCK_TTL` | `10800` (3 hours) | Seconds after the last IC action that a lock lapses; `None` to disable |
| `RP_CHARGEN_REQUIRE_APPROVAL` | `False` | Make approval a gate |
| `RP_CHARGEN_RPTRACKER_APP_LABEL` | `"evennia_rptracker"` | The tracker whose session end releases locks |
| `RP_CHARGEN_LOADOUT_BUDGET` | `None` | Total `budget_cost` of equipped abilities (`None`: no limit) |
| `RP_CHARGEN_LOADOUT_UNIT` | `"points"` | What the loadout budget is counted in |
| `RP_CHARGEN_STARTING_ALLOWANCE` | `0` | Every sheet's allowance, unless staff set one |
| `RP_CHARGEN_ALLOWANCE_NOUN` | `"starting allowance"` | What the allowance is called |
| `RP_CHARGEN_UPGRADE_COST` | `{"base": 1, "factor": 2}` | Upgrade *n* costs `base × factor^(n−1)` |
| `RP_CHARGEN_XP_LEDGER` | `None` | Dotted path to an XP ledger factory; without one, only the allowance pays |
| `RP_CHARGEN_CATALOG_SEED` | `None` | Dotted path to the catalog seed list |

System checks: `evennia_rp_chargen.E001` (the allocation can't be built or
doesn't fit the ruleset) and `E002` (a pip setting isn't a whole number).

---

## Roadmap

XP spending is available through the optional `evennia-xp>=0.2` ledger.
Combat will add its abilities as catalog entries using
new effect kinds, rather than defining an ability model of its own.
