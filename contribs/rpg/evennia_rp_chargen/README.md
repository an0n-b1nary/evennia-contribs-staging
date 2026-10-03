# evennia-rp-chargen

> **Preview (0.1.x, Pre-Alpha).** This package was written directly as a
> contrib rather than extracted from a running game, and its API will move
> while the rest of the rp- cluster is built on it. Pin an exact version.

Character sheets for RP-focused [Evennia](https://www.evennia.com) games,
built on [`evennia-rp-rules`](../evennia_rp_rules/README.md). It provides:

- graded stats chosen within an **allocation** (point-buy, array, or free);
- **edge** and **weakness** pips under a pip policy;
- a draft → finalized (→ approved) life cycle, with no staff bottleneck by
  default;
- **build locks** that freeze edge and loadout while a character is in a scene.

Stat names, rungs and numbers all come from the game's ruleset; this package
ships none of its own.

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
| `+chargen`, `/list`, `/approve`, `/reopen`, `/setstat` | staff | List, view, approve and reopen sheets, and set any rating directly |

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

System checks: `evennia_rp_chargen.E001` (the allocation can't be built or
doesn't fit the ruleset) and `E002` (a pip setting isn't a whole number).

---

## Roadmap

The next release adds the ability catalog: tags, abilities and flaws, the
Memory-budgeted loadout, staff grants, and Domain Expertise as a `tag_bonus`
modifier that reaches checks through `ChargenSubject`. Spending XP on
abilities follows.
