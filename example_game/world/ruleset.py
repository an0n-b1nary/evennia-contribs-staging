# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The sandbox's ruleset: seven graded stats, D-S, with Edge and Weakness pips.

STATUS: SIGNED OFF 2026-10-02 for playtesting (see the decisions log at the
end of this docstring). Retune with the odds tool, run from `example_game/`,
and log any change below:

    python -m evennia_rp_rules.odds --ruleset world.ruleset --scores
    python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix success --pips -5,-2,0,3,5
    python -m evennia_rp_rules.odds --ruleset world.ruleset --detail "B+++" A --modifier score=+8

Nothing here is player-facing except names: players see grades, `+`/`-` pips
and outcome labels, never scores. Retuning never changes what a sheet shows.

How the numbers fit together
----------------------------

- Grades sit 20 points apart: D 0, C 20, B 40, A 60, S 80.
- Edge pips depreciate (5, 4, 3, 2, 2: 16 points for all five) and are worth
  less on higher grades (factor 1.0 at D down to 0.6 at S), so `D +++++` is
  most of the way to C (16 of 20) while `S +++++` is under half a grade (9.6).
  The last two pips are equal so the fifth still counts on S (2 x 0.6 = 1.2);
  a pip worth under a point can play identically to the one before (W001).
- Weakness pips bite progressively (1, 2, 4, 5, 6: 18 for all five). The first
  is nearly flavour; the fifth hurts. Rung factors don't soften weakness.
- Neither can reach the neighbouring grade: the ruleset fails validation (E003)
  if a retune makes that possible.
- Noise is `1d100-1d100`: a triangle from -99 to +99 centred on 0 (sd ~41).
  Grades are gentle rather than decisive: even match ~51% success; one grade
  up ~32%; two up ~18%; three up ~8%; four up (D vs S) ~2%.
- Bands (applied to margin = your score - difficulty + noise) mirror around
  zero: Critical Success >= 66, Success >= 20, Narrow Success >= 0,
  Narrow Failure >= -20, Failure >= -65, Critical Failure below. "Narrow" means
  within one grade's worth (20) either way. An even match comes out roughly
  6 / 26 / 18 / 18 / 26 / 6 percent from Critical Failure up to Critical Success.

Decisions log
-------------

2026-10-02, first sign-off pass:

- Added Narrow Failure, mirroring Narrow Success: fun for roleplay.
- Noise 3d40-3d40 -> 1d100-1d100. Grades needn't be so decisive; ~32% one
  grade up feels right. Bands rescaled to the six-outcome ladder above.
- Two S grades stay possible under point-buy: absurdly statted is a choice.
- Challenge difficulties may carry pips (`A+`, `B--`).
- Default difficulty C.
- XP costs and the starting allowance are placeholders until the ability
  catalog (P3); expect fine-tuning there.
- Elements set (since replaced; see below). Domains add Acrobatics, Alchemy,
  Insight, Seduction, Thievery; Craft renamed Tinkering.
- Unchanged from the first proposal, open to revision: grade spacing, Edge
  and Weakness curves, rung factors, Domain Expertise +8 / +1 per level / max 5.

2026-10-02, signed off:

- Six-outcome bands confirmed as above.
- Domain Expertise stays +8 until playtesting says otherwise. At this noise
  width Edge and Expertise move fewer percentage points than they would with
  decisive grades; Edge can't grow (E003 caps it under a grade), so Expertise
  is the lever if specialists need to stand out more.

2026-10-02, elements:

- Elements are now the conventional Fire, Water, Air, Earth, Light and
  Darkness. The earlier list was specific to one setting, and this sandbox
  is a generic reference game. A game swaps in its own elements; nothing in
  the contribs depends on which exist.

2026-10-02, abilities (P3):

- Abilities wait for combat; for now the catalog is Domain Expertise only.
- Families are templates, acquired once per tag: one Domain Expertise entry
  covers every domain, including ones staff add later.
- Flaws start as templated inversions of Domain Expertise, Resistance and
  Receptivity, at -8 (mirroring Expertise's base). The Receptivity flaw has
  no effect until support abilities exist.
- Players spend their starting allowance on abilities from P3; XP joins as
  the second source of payment in P6.
"""

RULESET = {
    "version": "sandbox-1",
    "scales": {
        "grade": {
            "name": "Grade",
            "rungs": [
                {"key": "d", "label": "D", "score": 0},
                {"key": "c", "label": "C", "score": 20, "edge_factor": 0.9},
                {"key": "b", "label": "B", "score": 40, "edge_factor": 0.8},
                {"key": "a", "label": "A", "score": 60, "edge_factor": 0.7},
                {"key": "s", "label": "S", "score": 80, "edge_factor": 0.6},
            ],
            "edge": [5, 4, 3, 2, 2],
            "weakness": [1, 2, 4, 5, 6],
        },
    },
    "stats": [
        {
            "key": "prowess",
            "name": "Prowess",
            "category": "physical",
            "description": "Physical power: force, feats of strength, hitting hard.",
        },
        {
            "key": "toughness",
            "name": "Toughness",
            "category": "physical",
            "description": "Physical resilience: endurance, shrugging off hardship and harm.",
        },
        {
            "key": "magic",
            "name": "Magic",
            "category": "magical",
            "description": "Magical power: working spells and bending magic to purpose.",
        },
        {
            "key": "aura",
            "name": "Aura",
            "category": "magical",
            "description": "Magical resilience: warding off and weathering magic.",
        },
        {
            "key": "charisma",
            "name": "Charisma",
            "category": "social",
            "description": (
                "Affecting things without force: presence, allure, cunning, "
                "opportunism, dynamism, leadership."
            ),
        },
        {
            "key": "will",
            "name": "Will",
            "category": "social",
            "description": "Resolve and composure: holding steady under pressure.",
        },
        {
            "key": "agility",
            "name": "Agility",
            "category": "physical",
            "description": "Speed, reflexes and deftness.",
        },
    ],
    # Seed vocabulary only; chargen's DB vocabulary grows from here at runtime
    # as players propose new tags. Candidate list, not a closed set.
    "tags": [
        {"key": "acrobatics", "name": "Acrobatics"},
        {"key": "alchemy", "name": "Alchemy"},
        {"key": "athletics", "name": "Athletics"},
        {"key": "deception", "name": "Deception"},
        {"key": "insight", "name": "Insight"},
        {"key": "intimidation", "name": "Intimidation"},
        {"key": "medicine", "name": "Medicine"},
        {"key": "perception", "name": "Perception"},
        {"key": "performance", "name": "Performance"},
        {"key": "persuasion", "name": "Persuasion"},
        {"key": "scholarship", "name": "Scholarship"},
        {"key": "seduction", "name": "Seduction"},
        {"key": "stealth", "name": "Stealth"},
        {"key": "survival", "name": "Survival"},
        {"key": "thievery", "name": "Thievery"},
        {"key": "tinkering", "name": "Tinkering"},
        {"key": "fire", "name": "Fire", "kind": "element"},
        {"key": "water", "name": "Water", "kind": "element"},
        {"key": "air", "name": "Air", "kind": "element"},
        {"key": "earth", "name": "Earth", "kind": "element"},
        {"key": "light", "name": "Light", "kind": "element"},
        {"key": "darkness", "name": "Darkness", "kind": "element"},
    ],
    # Degrees mirror around zero: the sign says success or failure, the size
    # says by how much.
    "outcomes": [
        {"key": "critical_failure", "label": "Critical Failure", "degree": -3, "success": False},
        {"key": "failure", "label": "Failure", "degree": -2, "success": False},
        {"key": "narrow_failure", "label": "Narrow Failure", "degree": -1, "success": False},
        {"key": "narrow_success", "label": "Narrow Success", "degree": 1, "success": True},
        {"key": "success", "label": "Success", "degree": 2, "success": True},
        {"key": "critical_success", "label": "Critical Success", "degree": 3, "success": True},
    ],
    "resolver": {
        "path": "evennia_rp_rules.resolvers.GradedResolver",
        "params": {
            "noise": "1d100-1d100",
            "bands": [
                {"outcome": "critical_success", "min": 66},
                {"outcome": "success", "min": 20},
                {"outcome": "narrow_success", "min": 0},
                {"outcome": "narrow_failure", "min": -20},
                {"outcome": "failure", "min": -65},
                {"outcome": "critical_failure"},
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# Candidate numbers for later phases. Not read by anything yet: each block
# names the phase that will wire it into settings. Kept here so the whole
# rules sign-off happens in one file.
# ---------------------------------------------------------------------------

# P1/P3: Domain Expertise is a flat score bonus on tests tagged with its
# domain. Upgrades are an XP dump: they do something, just not much.
DOMAIN_EXPERTISE = {"score": 8, "per_level": 1, "max_level": 5, "memory": 10}

# P2: point-buy stat allocation during the draft stage. Escalating costs make
# stacking expensive; the budget buys "all B" or a specialised spread such as
# S B B B C D D, A A A B D D D, or even S S D D D D D (allowed on purpose).
POINT_BUY = {"costs": {"d": 0, "c": 1, "b": 2, "a": 4, "s": 7}, "budget": 14}

# P2: pip policy (from the design: 10 Edge total, 5 per stat; weakness free).
PIPS = {"edge_budget": 10, "edge_cap": 5, "weakness_cap": 5}

# P3: ability loadout budget.
MEMORY_BUDGET = 100

# P4: difficulty used when `+test` names no challenge, and whether a challenge
# may carry pips (`+test/set A+=...`, `B--`) for finer storyteller control.
DEFAULT_DIFFICULTY = "C"
DIFFICULTY_ALLOWS_PIPS = True

# P3/P6: XP. PLACEHOLDERS until the ability catalog is written; expect tuning.
# The starting allowance is spent before earned XP and never counts toward XP
# totals. Upgrade n (1-based) costs `base * factor ** (n - 1)`.
STARTING_ALLOWANCE = 10
ABILITY_XP_COST = {"domain_expertise": 3}
UPGRADE_COST = {"base": 2, "factor": 2}

# P3: the ability catalog seed (RP_CHARGEN_CATALOG_SEED = "world.ruleset.CATALOG").
# Only Domain Expertise for now; the full list waits for combat. Every entry is
# a template, acquired once per domain ("Domain Expertise: Performance"), so a
# domain added at runtime is available at once. The flaws invert Expertise,
# Resistance and Receptivity: free, self-service, always in effect.
FLAW_PENALTY = DOMAIN_EXPERTISE["score"]

CATALOG = [
    {
        "key": "domain-expertise",
        "name": "Domain Expertise",
        "category": "domain",
        "tag_kind": "domain",
        "acquisition": "xp",
        "xp_cost": ABILITY_XP_COST["domain_expertise"],
        "max_level": DOMAIN_EXPERTISE["max_level"],
        "budget_cost": DOMAIN_EXPERTISE["memory"],
        "description": "A bonus on every test in the domain, growing a little with each level.",
        "effects": [
            {
                "kind": "tag_bonus",
                "tags": ["@tag"],
                "score": DOMAIN_EXPERTISE["score"],
                "per_level": DOMAIN_EXPERTISE["per_level"],
            }
        ],
    },
    {
        "key": "domain-ineptitude",
        "name": "Domain Ineptitude",
        "category": "domain",
        "tag_kind": "domain",
        "is_flaw": True,
        "acquisition": "free",
        "description": "Expertise turned inside out: a penalty on your own tests in the domain.",
        "effects": [{"kind": "tag_bonus", "tags": ["@tag"], "score": -FLAW_PENALTY}],
    },
    {
        "key": "domain-vulnerability",
        "name": "Domain Vulnerability",
        "category": "domain",
        "tag_kind": "domain",
        "is_flaw": True,
        "acquisition": "free",
        "description": (
            "Resistance turned inside out: a penalty when someone else's opposed test "
            "against you is in the domain."
        ),
        "effects": [
            {"kind": "tag_bonus", "tags": ["@tag"], "score": -FLAW_PENALTY, "match": "opposing"}
        ],
    },
    {
        "key": "domain-aversion",
        "name": "Domain Aversion",
        "category": "domain",
        "tag_kind": "domain",
        "is_flaw": True,
        "acquisition": "free",
        "description": (
            "Receptivity turned inside out: help in the domain does you less good. No "
            "effect yet; it takes hold once support abilities exist."
        ),
        "effects": [],
    },
]
