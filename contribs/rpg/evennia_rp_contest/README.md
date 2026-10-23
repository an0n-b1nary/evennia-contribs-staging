# evennia-rp-contest

Hosts may bind one-off attempts to another system through `bound.snapshot`,
`bound.approaches`, `bound.perform` and `bound.validate`. Snapshots fold ratings
and modifiers at the host's build lock; later attempts use that frozen source
and the authored difficulty. `perform` requires the host's atomic transaction;
the host enforces authorization, uniqueness and journaling. These attempts
create normal private audit records with a binding, without room-challenge
matching or award signals. Public history renders them without ratings even
when ordinary room tests reveal ratings. Staff review retains the breakdown.

> **Preview (0.2.0, Pre-Alpha).** Authored directly as a contrib-native pilot.
> APIs and migrations may change; pin an exact commit.

Non-combat stat checks and room challenges, with no game-specific stat names,
grades or rewards. It requires `evennia-rp-rules` and `evennia-links`, but not
chargen or combat. See [MIGRATION_NOTES.md](MIGRATION_NOTES.md) for origin and
adoption steps, and [`example_game`](../../../example_game/README.md) for the
wired reference integration.

Install the dependencies before this package, add `evennia_rp_contest` after
them in `INSTALLED_APPS`, run `evennia migrate --noinput`, and add
`evennia_rp_contest.commands.ContestCmdSet` to your character cmdset.
Configure the kernel's ruleset, subject adapter and vocabulary. Chargen's
`evennia_rp_chargen.subject.subject_adapter` and
`evennia_rp_chargen.vocabulary.DBVocabulary` can supply the latter two;
alternatively use a game adapter returning `DictStatSource` and the default
ruleset vocabulary. Character typeclass changes are unnecessary.

```
+test <stat>[/<tag>] [# comment]
+test #n=<stat>[/<tag>] [# comment]
+challenge
+challenge/new <difficulty>=<prompt>
+challenge/suggest #n=<stat>[/<tag>]
+challenge/edit #n=<prompt>
+challenge/difficulty #n=<difficulty>
+challenge/once #n
+challenge/void #n.<attempt id> [# reason]
+challenge/close #n
+challenge/history [#n]
+challenge/review [#n]   (staff)
```

Suggestions are optional guidance. Players may choose any approach, including
an element. Departures are marked "alternative approach". An unnumbered test
always uses the default difficulty; `#n=` explicitly answers a room challenge.
A comment starts at the first whitespace-surrounded `#`, preserving references
such as `#12` and all later comment text.

Numbers are per room and never reused. `/edit`, `/difficulty` and `/suggest`
change only the prompt, difficulty and suggested approach respectively; the
other fields and prior attempt records remain unchanged. `/once` marks an open
challenge as one attempt per character. `/new` is available to everyone by
default; managing a challenge requires its setter or staff. `/void` takes the
unique **attempt id shown in /history**, because multiple characters may each
have an "attempt 1". It retains the record, stops it counting toward `/once`,
and announces the decision. A retry keeps its increasing attempt number.
Each command accepts at most one switch, including unambiguous prefixes.

Room lines hide ratings and dice. The tester sees their ratings privately;
only staff /review sees the complete ledger, noise, resolver and ruleset digest.
History shows at most the 50 most recent room attempts, including voids.
Player text is passed as mapping values to real `msg_contents`; braces and
FuncParser calls in that text cannot become executable templates. Messages
carry `{"type": "rp_test"}`. No XP or other awards are given.

Settings (defaults):

| Setting | Default |
| --- | --- |
| `RP_CONTEST_STAFF_LOCK` | `cmd:perm(Builder)` |
| `RP_CONTEST_CAN_SET_CHALLENGE` | `cmd:all()` |
| `RP_CONTEST_DEFAULT_DIFFICULTY` | `None` (middle rung of the chosen stat scale) |
| `RP_CONTEST_DIFFICULTIES` | `{}` (preset name → rating text) |
| `RP_CONTEST_TAG_KIND` | `["domain", "element"]`; a single kind or `None` (any) also works |
| `RP_CONTEST_NARRATION` | `evennia_rp_contest.narration.announce_test` |
| `RP_CONTEST_SHOW_RATINGS_TO_ROOM` | `False` |
| `RP_CONTEST_COMMENT_MAX` | `500` (comments, prompts and void reasons) |
| `RP_CONTEST_CHALLENGE_IDLE_TTL` | `10800` seconds; `timedelta` or `None` also accepted |
| `RP_CONTEST_SCENE_ID_RESOLVER` | `None`; callable path taking the caller |
| `RP_CONTEST_SCENES_APP_LABEL` | `evennia_scenes` |
| `RP_CONTEST_RPTRACKER_APP_LABEL` | `evennia_rptracker` |

Tag lookup accepts keys, names, aliases and unique prefixes across the allowed
kinds. Ambiguous spellings ask which tag was meant; `kind:key` selects one.
Custom narration receives `record, result=...`; use `narration.emit` with a
trusted template and a mapping for all player text.

`services.perform_test(caller, request, roller=...)` resolves and records a test.
`parsing.parse_test` / `parse_challenge` produce requests. The public signals
are `check_recorded`, `check_voided`, `challenge_opened`, `challenge_edited`
and `challenge_closed`; their payloads are documented in `signals.py`.

Optional scenes integration records public SYSTEM lines, closes challenges
when scenes close, and detaches scene ids on hard deletion while retaining
audit records. Tracker session end closes the setter's challenges. Both
integrations are gated in `AppConfig.ready()`; absent partners have no model
or migration dependencies. A custom game can wire `expiry.close_for_scene`,
`expiry.close_for_setter` and `check_recorded` itself.

Commands lazily sweep idle challenges. To close them during quiet periods,
schedule `expiry.sweep_idle()` using your game's ticker or maintenance job.
Without scenes, tests have no scene id. Without tracker, manual close and
idle expiry continue to work. Uninstalling chargen only requires changing
your kernel subject adapter and vocabulary settings.

CI runs this suite with all partners, without each individual partner, and
without all three. In a fresh venv, use `scripts/ci_install_contribs.py` with
`--exclude` for absent partners, migrate the disposable game, then run
`python scripts/ci_run_rp_contest_tests.py <game> --absent <app_label>`.
The runner refuses an allegedly absent partner that is still importable and
an Evennia launcher that exits without a positive test count.

## Guide pages

The staff-only [`contest-staff`](guides/contest-staff.md) page covers staff tasks, command permissions, safe changes, privacy and review queues. It stays readable by guide staff before player systems are revealed.

The `guides/` directory holds player and staff guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `tests`,
`defaults-with-override` (a principle). They explain the system to players in
general terms, without exact numbers, and link only to pages this contrib or
its required dependencies ship. With evennia-guides installed they appear on
its web guide; without it they're ignored. To restate one for your game, add a
page with the same key to `GUIDES_DIRS`.

## Disposable guests

Guest practice checks have no persistent audit record, challenge attempt or result signals. Guests cannot create or manage shared challenges.

Guest identity comes from `evennia_links.guests.is_guest`, using the actual
account typeclass and playable ownership rather than a hierarchical Guest
permission check. See the reference game for restricted command composition.
