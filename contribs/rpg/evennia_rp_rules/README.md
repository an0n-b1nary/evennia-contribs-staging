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
pass on an impossible roll.

---

## Roadmap

The next release adds the check pipeline: stat subjects, a frozen `Check`,
phase-hooked modifiers (`ScoreBonus`, `TagBonus`, `RungShift`) folded
commutatively, a `check_resolved` signal, and system checks that surface the
validation table above at startup.
