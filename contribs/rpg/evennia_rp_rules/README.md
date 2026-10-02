# evennia-rp-rules

> **Preview (0.1.x, Pre-Alpha).** This package was written directly as a
> contrib rather than extracted from a running game, and its API will move
> while the rest of the rp- cluster is built on it. Pin an exact version.

The value-neutral resolution kernel for RP-focused [Evennia](https://www.evennia.com)
games: graded stats with **edge** and **weakness** pips, a shared **outcome
ladder**, pluggable **resolvers**, seedable **dice**, and an exact **odds
tool** for tuning.

It ships no models, no commands, and no stat names. A game describes its rules
as a plain dict (a *ruleset*) and the kernel validates and runs it. The planned
`evennia-rp-chargen` (character sheets), `evennia-rp-contest` (`+test`
challenges) and, later, `evennia-rp-combat` all resolve through it, so
non-combat checks and combat share one set of numbers without importing each
other.

---

## Concepts

**Scale.** An ordered ladder of rungs, such as grades `D C B A S` or ranks
`Novice … Legend`. Each rung has a hidden numeric score. Players see the rung,
and the resolver works with the score.

**Rating.** A rung plus pips: `B +++` has three edge, and `B +++ -` also has
one weakness. Pips are *piecewise*: the scale defines an increment curve for
edge and another for weakness, and the *n*th pip is worth the *n*th increment.
That lets extra edge depreciate (`[5, 4, 3, 2, 1]`) and extra weakness bite
harder (`[2, 3, 3, 4, 5]`). Each rung can also scale its pips
(`edge_factor`, `weakness_factor`), so pips matter less on high rungs.

Edge and weakness combine by **net** count. `+++ -` is valued as two net edge
on the edge curve; `+ ---` is two net weakness on the weakness curve. Both
counts stay on the rating, so a sheet can show the flavour choice
(`B +++ -`, edge first).

**Pips never cross a rung.** At full edge a rung must still score strictly
below the next rung up, and at full weakness strictly above the next rung
down. This is validated, not hoped for (see E003 below). Bonuses from
abilities are not pips and aren't bound by it.

**Outcome ladder.** The ruleset's ordered outcomes (for example Critical
Failure → Failure → Partial Success → Success → Critical Success). Each has a
unique integer `degree` (higher is better) and an explicit `success` flag. Every
resolver lands on this one ladder.

**Resolver.** It turns a `Contest` (an actor rating against a target rating,
plus flat bonuses) into an outcome. The reference `GradedResolver` computes:

```
margin  = (actor score + bonus) - (target score + bonus) + noise roll
outcome = the first band, best first, whose `min` the margin reaches
```

The noise is any dice expression (`1d20`, `2d6-7`, `3d20-3d20`). Opposed
contests can roll different noise (`opposed_noise`). Resolvers take a
`Roller`, so tests script exact rolls and nothing touches a module-level RNG.

---

## Quick start

```bash
pip install evennia-rp-rules
```

```python
# server/conf/settings.py
INSTALLED_APPS += ["evennia_rp_rules"]
RP_RULES_RULESET = "world.ruleset"   # a module with a RULESET dict
```

Start from the bundled example: copy `evennia_rp_rules/example_ruleset.py` to
`world/ruleset.py`, rename the stats and rungs, then tune it with the odds tool
(below). Without the setting, the example ruleset is used.

```python
from evennia_rp_rules import Contest, ScriptedRoller, get_ruleset

rules = get_ruleset()
contest = Contest(rules.parse_rating("Adept+++"), rules.parse_rating("Expert"))
rules.resolver.estimate(contest).success      # exact Fraction
result = rules.resolver.resolve(contest)      # live roll
result.outcome.label, result.as_dict()        # JSON-safe record
```

---

## The ruleset spec

```python
RULESET = {
    "version": "2026-10",                     # your label; recorded with every check
    "scales": {
        "grade": {
            "name": "Grade",
            "rungs": [                        # lowest first, strictly increasing scores
                {"key": "d", "label": "D", "score": 0},
                {"key": "c", "label": "C", "score": 20},
                {"key": "b", "label": "B", "score": 40, "edge_factor": 0.9},
                # ...
            ],
            "edge": [5, 4, 3, 2, 1],          # its length is the most edge a rating may carry
            "weakness": [2, 3, 3, 4, 5],
            "glyphs": {"edge": "+", "weakness": "-"},   # optional
        },
    },
    "default_scale": "grade",                 # optional with a single scale
    "stats": [
        {"key": "presence", "name": "Presence", "aliases": ["pre"], "description": "..."},
    ],
    "tags": [                                 # optional; no intrinsic effect
        {"key": "persuasion", "name": "Persuasion", "kind": "domain"},
        {"key": "fire", "name": "Fire", "kind": "element"},
    ],
    "outcomes": [
        {"key": "failure", "label": "Failure", "degree": -1, "success": False},
        {"key": "success", "label": "Success", "degree": 1, "success": True},
    ],
    "resolver": {
        "path": "evennia_rp_rules.resolvers.GradedResolver",   # the default
        "params": {
            "noise": "3d20-3d20",
            "opposed_noise": "3d20-3d20",     # optional
            "bands": [
                {"outcome": "success", "min": 0},
                {"outcome": "failure"},       # the last band catches everything below
            ],
        },
    },
}
```

Numbers may be ints, floats, decimals or strings. They're held as exact
fractions, so boundaries and the crossing check never wobble on float
rounding.

### Validation

`Ruleset.from_spec()` reports **every** problem at once:

| Id | Level | Meaning |
|---|---|---|
| E001 | error | Malformed: missing or ill-typed fields, bad keys, duplicates, ambiguous spellings |
| E002 | error | Inconsistent: unknown scale or outcome references, unimportable resolver, bad resolver parameters |
| E003 | error | Pips can cross a rung, in either direction |
| W001 | warning | A pip changes no odds. Whole-number dice only resolve whole points, so a pip worth a fraction of a point after rung factors can do nothing at all |

With the app installed, the same table runs as Django system checks
(`evennia_rp_rules.E003` and so on) at startup, so a broken ruleset stops the
server instead of misbehaving in play. One more check covers settings:

| Id | Level | Meaning |
|---|---|---|
| W002 | warning | An `RP_RULES_*` dotted path can't be imported, or isn't the right shape |

---

## Checks

A **check** is one stat tested against a stated difficulty or an opponent:

```python
from evennia_rp_rules import Check, estimate_check, resolve_check

check = Check("test", ana, "charisma", tags={"performance"}, difficulty="A")
result = resolve_check(check)                  # rolls, fires check_resolved
result.outcome.label                           # "Narrow Success"
[e.describe() for e in result.entries_for("actor")]   # ["Expertise: Performance +8"]
estimate_check(check, viewer="actor").odds.success    # exact, nothing rolled
```

- `kind` names the system asking (`"test"`; combat will use its own), so
  modifiers and listeners can tell checks apart without importing each other.
- The actor and opponent can be anything with stats; see *Subjects* below.
  An opposed check (`opponent=...`, optionally `opponent_stat=` and
  `opponent_tags=`) rolls the ruleset's `opposed_noise`.
- `CheckError` carries a message fit to show the player: an unknown stat, a
  character without that stat, a difficulty that doesn't parse.
- `result.as_dict()` is a JSON-safe record of everything, including entries
  only staff may see. Store it and filter later with `entries_for(viewer)`.
- `check_resolved` (in `evennia_rp_rules.signals`) fires after every resolved
  check, with `check` and `result`. It doesn't fire for estimates. A receiver
  that raises propagates, so a game can wrap the check and its record in one
  transaction.

### Subjects

The kernel never reads a character's attributes. It asks a **stat source**:

```python
class StatSource(Protocol):
    def get_rating(self, stat_key) -> Rating | str | None: ...
    def get_modifiers(self, check) -> Iterable[Modifier]: ...   # optional
```

`get_subject(obj)` uses `obj` itself if it has `get_rating`. Otherwise it asks
`RP_RULES_SUBJECT_ADAPTER(obj)`, and finally wraps a plain dict in a
`DictStatSource`. Characters need no typeclass changes, and an NPC can be a
stat block: `DictStatSource({"prowess": "A+"}, modifiers=[...])`.

### Modifiers and the pipeline

A modifier is anything that bends a check, such as an ability bonus, a flaw or
a storyteller's call. Combat will later add stances and riders. Each one
declares:

- the **phases** it hooks;
- whether it **applies** to a given check;
- its **visibility**;
- and what it adds, through `ctx.add(score=..., rung=...)`.

```python
class Inspired(BaseModifier):
    key, label = "inspired", "Inspired"

    def applies(self, ctx):
        return ctx.stat.key == "charisma"

    def apply(self, phase, ctx):
        ctx.add(score=3)
```

A check runs **BUILD**, then **PRE_RESOLVE** (which sees what BUILD added),
rolls, then **ON_OUTCOME** (which sees the outcome and may add notes, but
can't change numbers). `DECLARE`, `OFFER_REACTIONS` and `REACTION_CHOSEN` are
reserved for combat and never run in a check.

**Order never changes a number.** Within a phase, every modifier sees the
state as it was when the phase began, and each side's total is a sum. So the
same modifiers give the same result whichever order the providers return them
in. Entries that share a `stack` name don't stack: only the strongest counts,
and the others stay in the ledger marked *not applied*.

Modifiers are collected from the actor's subject, the opponent's subject, every
callable in `RP_RULES_MODIFIER_PROVIDERS` (`provider(check) -> modifiers`) and
the check's own `modifiers=`.

**Visibility** decides who sees a modifier, and so whose estimate counts it:

| Visibility | Seen by | Example |
|---|---|---|
| `open` | anyone shown the breakdown | Domain Expertise |
| `hidden` | staff and the side that owns it | an attacker's feint |
| `secret` | staff only | a storyteller's private thumb on the scale |

`estimate_check(check, viewer=...)` leaves out what the viewer can't see, so
an estimate is exactly as good as what the viewer knows. Resolution always
counts everything.

### Effect kinds

Catalog data becomes a modifier through `build_modifier(spec, level=...)`:

```python
build_modifier({"kind": "tag_bonus", "tags": ["performance"], "score": 8, "per_level": 1},
               level=3, key="expertise-performance", label="Expertise: Performance")
# +10 on any check tagged Performance
```

| Kind | Fields | Effect |
|---|---|---|
| `score_bonus` | `score`, `per_level`; filters `stats`, `tags` | Flat score bonus or penalty |
| `tag_bonus` | `tags` (required), `score`, `per_level`; filter `stats` | Bonus on checks sharing a tag (Domain Expertise) |
| `rung_shift` | `steps`; filters `stats`, `tags` | Whole rungs up or down, pips kept, clamped |

Every kind also takes `key`, `label`, `visibility`, `priority`, `stack` and
`check_kinds` (for example `["test"]`). A bonus isn't a pip, so it may carry a
rating past the next rung.

Add your own kinds with `RP_RULES_EFFECT_KINDS = {"kind": "path.to.Class"}`.
The class needs a `from_spec(spec, *, level, **meta)` classmethod that raises
`EffectSpecError` on bad data. `effect_problems(spec, vocabulary=..., ruleset=...)`
lists every problem with a spec, including unknown tags and stats, for a
catalog's `clean()`.

### Tag vocabulary

The ruleset's `tags` are a seed. `get_vocabulary()` returns
`RP_RULES_VOCABULARY()` if that's set; chargen's database vocabulary is one
example, letting staff add a domain without a deploy. Otherwise it returns
the ruleset's own tags. Commands resolve player input with
`get_vocabulary().find(text, kind="domain")`. The pipeline treats tags as
opaque keys.

---

## The odds tool

Exact enumeration, with no simulation and no Django. Run it from your game
directory so `world.ruleset` imports:

```bash
python -m evennia_rp_rules.odds --ruleset world.ruleset --scores
python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix success --pips -2,0,3,5
python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix critical_success+
python -m evennia_rp_rules.odds --ruleset world.ruleset --detail "B+++" A --modifier score=+4
python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix success --markdown
```

- `--scores` shows each rung's hidden score at every net pip count. It still
  works on a ruleset that fails E003 and marks the crossing cells with `!`.
- `--matrix W` shows the chance of `W` for each actor rating against each
  target rung. `W` is `success`, `failure`, an outcome key, or `KEY+` for that
  outcome or better.
- `--detail A T` shows one matchup: both scores, the noise range, and the rolls
  and chance for each outcome.
- `--modifier score=N` and `--modifier rung=N` adjust the actor, and
  `--target-modifier` adjusts the target. `--opposed` uses opposed noise.

---

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `RP_RULES_RULESET` | `"evennia_rp_rules.example_ruleset"` | A dict, a module (its `RULESET`), a `module.ATTR` path, or a `.py` file |
| `RP_RULES_SUBJECT_ADAPTER` | unset | Dotted path to `adapter(obj)`, returning a stat source or `None` |
| `RP_RULES_MODIFIER_PROVIDERS` | `[]` | Dotted paths to `provider(check)`, each returning modifiers |
| `RP_RULES_EFFECT_KINDS` | `{}` | `{kind: "path.to.Class"}`, added to the built-in kinds |
| `RP_RULES_VOCABULARY` | unset | Dotted path to a zero-argument factory returning a vocabulary |
| `RP_RULES_ROLLER` | unset | Dotted path to a zero-argument factory returning a roller (default `RandomRoller()`) |

Every setting is read when it's needed, and the defaults apply when Django
isn't configured. A script can therefore resolve checks with an explicit
`ruleset=` and `roller=`.

`get_ruleset()` caches the built ruleset. The cache clears whenever an
`RP_RULES_*` setting changes, including under `override_settings`.

---

## Testing helpers

```python
from django.test import SimpleTestCase
from evennia_rp_rules import Contest
from evennia_rp_rules.testing import RulesetTestMixin

class MyTests(RulesetTestMixin, SimpleTestCase):
    def test_something(self):
        contest = Contest(self.ruleset.parse_rating("Mid"), self.ruleset.parse_rating("Mid"))
        result = self.ruleset.resolver.resolve(contest, self.scripted(0))
        assert result.outcome.key == "good"
```

`TEST_RULESET` is tiny and round-numbered for hand-checkable expectations.
`ScriptedRoller` refuses totals the dice couldn't produce, so a test can't
pass on an impossible roll. `ProbeSubject` is a stat block that records every
check it was asked for modifiers on.

---

## Roadmap

`evennia-rp-chargen` (character sheets, abilities, build locks) and
`evennia-rp-contest` (`+test` challenges) are built on this release. Combat
will add the reserved phases' behaviour (declarations, reaction offers) and an
action/reaction layer on top of the same checks, modifiers and outcome ladder.
