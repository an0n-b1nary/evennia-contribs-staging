# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""The sandbox's ruleset: seven graded stats, D-S, with + and weakness pips.

STATUS: SIGNED OFF 2026-10-02 for playtesting (see the decisions log at the
end of this docstring). Retune with the odds tool, run from `example_game/`,
and log any change below:

    python -m evennia_rp_rules.odds --ruleset world.ruleset --scores
    python -m evennia_rp_rules.odds --ruleset world.ruleset --matrix success --pips -5,-2,0,3,5
    python -m evennia_rp_rules.odds --ruleset world.ruleset --detail "B+++" A --modifier score=+8

Nothing here is player-facing except names: players see grades, `+`/`-` pips
and outcome labels, never scores. Retuning never changes what a sheet shows.
Every name is the game's to change; a sheet stores keys, never names.

How the numbers fit together
----------------------------

- Grades sit 20 points apart: D 0, C 20, B 40, A 60, S 80.
- `+` pips depreciate (5, 4, 3, 2, 2: 16 points for all five) and are worth
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

2026-10-05, vocabulary and sandbox playtest:

- Wit and Sensitivity replace Magic and Aura. Methodical work belongs to
  Will; cunning belongs to Wit.
- Sixteen domains include Ritual. Scholarship covers natural philosophy
  and magitech; Alchemy covers identifying and handling substances.
- Suggested stats guide an approach; any stat/tag pairing is allowed.
- Elemental Focus mirrors Domain Expertise on the six conventional elements.
- Domain Receptivity and Aversion are retired. Resistance and Vulnerability
  remain, for both domains and elements.

2026-10-08, generic vocabulary (every number unchanged):

- Stats are the classic seven: Strength, Endurance and Agility (physical),
  Intellect and Intuition (mental), Presence and Resolve (social). They were
  Prowess, Toughness, Agility, Wit, Sensitivity, Charisma and Will. Intellect
  takes cunning; Resolve keeps methodical work.
- Fighting styles replace elements as the second tag kind (`style`): Blades,
  Blunt, Polearms, Archery, Unarmed and Spellcraft. A move has a style the
  way it would have an element, and a style is also a `+test` tag.
- Domain Expertise is Proficiency: a general benefit in combat (once combat
  exists) and a specific one on tests in its domain. Elemental Focus is
  Combat Focus, on a style: a specific benefit in combat and a general one
  on tests carrying the style. Resistance and Vulnerability exist for both
  kinds; Domain Ineptitude is Ineptitude.
- Edge pips are just pips, through the contrib's `+pips`; the loadout counts
  in the contrib's default "points". Scholarship and Ritual descriptions lose
  their setting-specific notes.
"""

RULESET = {
    "version": "sandbox-3",
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
            # The rules contrib calls + pips "edge" and - pips "weakness".
            "edge": [5, 4, 3, 2, 2],
            "weakness": [1, 2, 4, 5, 6],
        },
    },
    "stats": [
        {
            "key": "strength",
            "name": "Strength",
            "category": "physical",
            "description": "Force, power, martial skill and finesse with a weapon.",
        },
        {
            "key": "endurance",
            "name": "Endurance",
            "category": "physical",
            "description": "Stamina: weathering pain, poison, cold and hardship.",
        },
        {
            "key": "intellect",
            "name": "Intellect",
            "category": "mental",
            "description": "Reasoning, knowledge, quick thinking and cunning.",
        },
        {
            "key": "intuition",
            "name": "Intuition",
            "category": "mental",
            "description": "Empathy, instinct, noticing and sensing the unseen.",
        },
        {
            "key": "presence",
            "name": "Presence",
            "category": "social",
            "description": "Charm, allure, leadership and performance.",
        },
        {
            "key": "resolve",
            "name": "Resolve",
            "category": "social",
            "description": "Discipline, patience, nerve and methodical work.",
        },
        {
            "key": "agility",
            "name": "Agility",
            "category": "physical",
            "description": "Speed, reflexes, balance and quick movement.",
        },
    ],
    # Seed vocabulary only; chargen's DB vocabulary grows from here at runtime
    # as players propose new tags. Suggested stats are guidance, not limits.
    "tags": [
        {
            "key": "acrobatics",
            "name": "Acrobatics",
            "description": "Balance, tumbling, falls and aerial movement. Suggested: Agility, Strength.",
        },
        {
            "key": "alchemy",
            "name": "Alchemy",
            "description": "Identifying and handling substances: potions, poisons and reagents. Suggested: Resolve, Intellect.",
        },
        {
            "key": "athletics",
            "name": "Athletics",
            "description": "Climbing, swimming, lifting, running and grappling. Suggested: Strength, Endurance.",
        },
        {
            "key": "deception",
            "name": "Deception",
            "description": "Lies, disguise, bluffing and forgery. Suggested: Intellect, Presence.",
        },
        {
            "key": "insight",
            "name": "Insight",
            "description": "Reading motives, lies and moods. Suggested: Intuition, Intellect.",
        },
        {
            "key": "intimidation",
            "name": "Intimidation",
            "description": "Threats, menace and interrogation. Suggested: Presence, Strength.",
        },
        {
            "key": "medicine",
            "name": "Medicine",
            "description": "Wounds, illness, diagnosis and surgery. Suggested: Intuition, Resolve.",
        },
        {
            "key": "perception",
            "name": "Perception",
            "description": "Noticing, searching and spotting danger. Suggested: Intuition, Intellect.",
        },
        {
            "key": "performance",
            "name": "Performance",
            "description": "Music, oratory, dance and acting. Suggested: Presence, Intuition.",
        },
        {
            "key": "persuasion",
            "name": "Persuasion",
            "description": "Argument, negotiation, diplomacy and rallying. Suggested: Presence, Intellect.",
        },
        {
            "key": "ritual",
            "name": "Ritual",
            "description": "Rites, wards, spirits and curses. Suggested: Resolve, Intuition.",
        },
        {
            "key": "scholarship",
            "name": "Scholarship",
            "description": "History, languages, law and natural philosophy. Suggested: Resolve, Intellect.",
        },
        {
            "key": "seduction",
            "name": "Seduction",
            "description": "Charm, allure and flirtation. Suggested: Presence, Intuition.",
        },
        {
            "key": "stealth",
            "name": "Stealth",
            "description": "Sneaking, hiding and shadowing someone. Suggested: Agility, Intuition.",
        },
        {
            "key": "survival",
            "name": "Survival",
            "description": "Wilderness, tracking, beasts, weather and hardship. Suggested: Endurance, Intuition.",
        },
        {
            "key": "thievery",
            "name": "Thievery",
            "description": "Pickpocketing, locks, palming and sleight of hand. Suggested: Intellect, Agility.",
        },
        # Fighting styles: a move has one, and any test may carry one too.
        {
            "key": "blades",
            "name": "Blades",
            "kind": "style",
            "description": "Swords, daggers and axes.",
        },
        {
            "key": "blunt",
            "name": "Blunt",
            "kind": "style",
            "description": "Maces, hammers, staves and clubs.",
        },
        {
            "key": "polearms",
            "name": "Polearms",
            "kind": "style",
            "description": "Spears, glaives and halberds.",
        },
        {
            "key": "archery",
            "name": "Archery",
            "kind": "style",
            "description": "Bows, crossbows and slings.",
        },
        {
            "key": "unarmed",
            "name": "Unarmed",
            "kind": "style",
            "description": "Fists, kicks, grapples and holds.",
        },
        {
            "key": "spellcraft",
            "name": "Spellcraft",
            "kind": "style",
            "description": "Battle magic: bolts, blasts and barriers.",
        },
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
# The sandbox settings import these values. Keep numeric tuning in one place.
# ---------------------------------------------------------------------------

# P1/P3: Proficiency is a flat score bonus on tests tagged with its domain.
# Upgrades are an XP dump: they do something, just not much.
PROFICIENCY = {"score": 8, "per_level": 1, "max_level": 5, "loadout_cost": 10}

# P2: point-buy stat allocation during the draft stage. Escalating costs make
# stacking expensive; the budget buys "all B" or a specialised spread such as
# S B B B C D D, A A A B D D D, or even S S D D D D D (allowed on purpose).
POINT_BUY = {"costs": {"d": 0, "c": 1, "b": 2, "a": 4, "s": 7}, "budget": 14}

# P2: pip policy (from the design: 10 + pips total, 5 per stat; weakness free).
PIPS = {"budget": 10, "cap": 5, "weakness_cap": 5}

# P3: ability loadout budget, in points.
LOADOUT_BUDGET = 100

# P4: difficulty used when `+test` names no challenge, and whether a challenge
# may carry pips (`+test/set A+=...`, `B--`) for finer storyteller control.
DEFAULT_DIFFICULTY = "C"
DIFFICULTY_ALLOWS_PIPS = True

# P6: XP costs and allowance; expect playtest tuning.
# The starting allowance is spent before earned XP and never counts toward XP
# totals. Upgrade n (1-based) costs `base * factor ** (n - 1)`.
STARTING_ALLOWANCE = 10
ABILITY_XP_COST = {"proficiency": 3}
UPGRADE_COST = {"base": 2, "factor": 2}

# P3: the ability catalog seed (RP_CHARGEN_CATALOG_SEED = "world.ruleset.CATALOG").
# Families are templates acquired once per tag. The combat-specific behavior
# waits for a combat contrib; these effects apply only to the shared RP checks.
FLAW_PENALTY = PROFICIENCY["score"]

CATALOG = [
    {
        "key": "proficiency",
        "name": "Proficiency",
        "category": "domain",
        "tag_kind": "domain",
        "acquisition": "xp",
        "xp_cost": ABILITY_XP_COST["proficiency"],
        "max_level": PROFICIENCY["max_level"],
        "budget_cost": PROFICIENCY["loadout_cost"],
        "description": "A bonus on every test in the domain, growing a little with each level.",
        "effects": [
            {
                "kind": "tag_bonus",
                "tags": ["@tag"],
                "score": PROFICIENCY["score"],
                "per_level": PROFICIENCY["per_level"],
            }
        ],
    },
    {
        "key": "combat-focus",
        "name": "Combat Focus",
        "category": "style",
        "tag_kind": "style",
        "acquisition": "xp",
        "xp_cost": ABILITY_XP_COST["proficiency"],
        "max_level": PROFICIENCY["max_level"],
        "budget_cost": PROFICIENCY["loadout_cost"],
        "description": "A bonus on tests carrying the fighting style, growing a little with each level.",
        "effects": [
            {
                "kind": "tag_bonus",
                "tags": ["@tag"],
                "score": PROFICIENCY["score"],
                "per_level": PROFICIENCY["per_level"],
            }
        ],
    },
    {
        "key": "domain-resistance",
        "name": "Domain Resistance",
        "category": "domain",
        "tag_kind": "domain",
        "acquisition": "xp",
        "xp_cost": ABILITY_XP_COST["proficiency"],
        "max_level": PROFICIENCY["max_level"],
        "budget_cost": PROFICIENCY["loadout_cost"],
        "description": "A bonus against someone else's opposed test carrying the domain.",
        "effects": [
            {
                "kind": "tag_bonus",
                "tags": ["@tag"],
                "score": PROFICIENCY["score"],
                "per_level": PROFICIENCY["per_level"],
                "match": "opposing",
            }
        ],
    },
    {
        "key": "style-resistance",
        "name": "Style Resistance",
        "category": "style",
        "tag_kind": "style",
        "acquisition": "xp",
        "xp_cost": ABILITY_XP_COST["proficiency"],
        "max_level": PROFICIENCY["max_level"],
        "budget_cost": PROFICIENCY["loadout_cost"],
        "description": "A bonus against someone else's opposed test carrying the fighting style.",
        "effects": [
            {
                "kind": "tag_bonus",
                "tags": ["@tag"],
                "score": PROFICIENCY["score"],
                "per_level": PROFICIENCY["per_level"],
                "match": "opposing",
            }
        ],
    },
    {
        "key": "ineptitude",
        "name": "Ineptitude",
        "category": "domain",
        "tag_kind": "domain",
        "is_flaw": True,
        "acquisition": "free",
        "description": "Proficiency turned inside out: a penalty on your own tests in the domain.",
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
        "key": "style-vulnerability",
        "name": "Style Vulnerability",
        "category": "style",
        "tag_kind": "style",
        "is_flaw": True,
        "acquisition": "free",
        "description": (
            "A penalty when someone else's opposed test against you carries the fighting style."
        ),
        "effects": [
            {"kind": "tag_bonus", "tags": ["@tag"], "score": -FLAW_PENALTY, "match": "opposing"}
        ],
    },
]
