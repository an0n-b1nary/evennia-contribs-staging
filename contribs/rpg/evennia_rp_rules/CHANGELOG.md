# Changelog — evennia-rp-rules

All notable changes to `evennia-rp-rules` will be documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- **Math core.**
  - `Scale` / `Rung` / `Rating`: piecewise edge and weakness pip curves with
    per-rung factors, net-pip scoring, `parse()` / `display()`.
  - `Outcome` / `OutcomeLadder` / `Odds`.
  - `DiceSpec`, `RandomRoller`, `ScriptedRoller`, and exact `distribution()`.
  - `Contest` / `Resolution` and the reference `GradedResolver`.
- **Ruleset spec.** `Ruleset.from_spec()` validates everything at once, using
  E001/E002/E003 and W001. It also provides stat/tag lookup, a digest,
  `get_ruleset()` with a settings-aware cache, and `load_ruleset_spec()`.
- **Pip invariants.**
  - E003: pips may never carry a rating across a rung, in either direction.
  - W001: warns when a pip is too small for whole-number dice to resolve.
- **`python -m evennia_rp_rules.odds`**: exact odds tables (`--scores`,
  `--matrix`, `--detail`, `--markdown`). It runs without Django.
- **`example_ruleset`**: a neutral default.
- **Checks.** A frozen `Check`, plus `resolve_check()` and `estimate_check()`.
  - Stated difficulties and opposed checks; opposed checks roll opposed noise.
  - `CheckResult` carries an itemised ledger, notes and a JSON-safe
    `as_dict()`; `entries_for(viewer)` filters what each viewer may see.
  - `CheckError` carries messages fit to show players.
  - The `check_resolved` signal fires after every resolved check.
- **Subjects.** The `StatSource` protocol, `DictStatSource` for NPC stat
  blocks, and `get_subject()` with `RP_RULES_SUBJECT_ADAPTER`.
- **Modifier pipeline.**
  - Phases `BUILD`, `PRE_RESOLVE` and `ON_OUTCOME`, with `DECLARE`,
    `OFFER_REACTIONS` and `REACTION_CHOSEN` reserved for combat.
  - Collection from both subjects, `RP_RULES_MODIFIER_PROVIDERS` and the
    check itself.
  - An order-independent fold: phase-start snapshots, summed entries, and
    non-stacking groups.
  - Open, hidden and secret visibility; estimates count only what their viewer
    may see.
- **Effect kinds.** `score_bonus`, `tag_bonus` and `rung_shift`, built from
  data by `build_modifier()`; games add kinds through `RP_RULES_EFFECT_KINDS`.
  `effect_problems()` validates specs against a vocabulary and ruleset.
  A tag filter's `match` can be `"opposing"` to resist the other side's
  tags.
- **Vocabulary.** `RulesetVocabulary` and `get_vocabulary()` with
  `RP_RULES_VOCABULARY`; `match_spelling()` resolves player input the same
  way for any vocabulary.
- **System checks.** Ruleset issues surface at startup as
  `evennia_rp_rules.E001`-`E003` and `W001`; W002 flags unresolvable
  `RP_RULES_*` paths.
- **`RP_RULES_ROLLER`** sets the default roller.
- **`testing`**: `TEST_RULESET`, `RulesetTestMixin` and `ProbeSubject`.
