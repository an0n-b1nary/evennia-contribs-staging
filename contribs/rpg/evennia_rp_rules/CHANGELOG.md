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
- **`testing`**: `TEST_RULESET` and `RulesetTestMixin`.
