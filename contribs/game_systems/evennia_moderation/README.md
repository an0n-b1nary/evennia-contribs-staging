# evennia-moderation

Account-wide timed bans, mutes, moderation history, private staff notes, and
reviewed guest admissions with caps and referral codes. Requires Evennia 6.0,
evennia-links 0.8.5 and evennia-jobs 0.7.2. No website dependency is required.

## Install

Install Links, Jobs, then Moderation. Add `evennia_moderation` after
`evennia_jobs` in `INSTALLED_APPS` and run `evennia migrate --noinput`.
See the reference integration in `example_game` for complete wiring.

Mix `ModerationAccountMixin` from `evennia_moderation.auth` before
`DefaultAccount`, and before `GuestAccountMixin`/`DefaultGuest` on guests.
Stock `connect` delegates to that typeclass: valid pending credentials show
status; approved credentials log in normally. Declined/lapsed applications
have no credentials and get the normal invalid-login response.

For website authentication, replace the stock backend and install the
middleware after Django's `AuthenticationMiddleware`:

```python
AUTHENTICATION_BACKENDS = ["evennia_moderation.auth.ModerationBackend"]
MIDDLEWARE += ["evennia_moderation.auth.ModerationMiddleware"]
```

The backend checks passwords and webclient autologin. Middleware rechecks
existing sessions and IP bans on each request. Account bans disconnect game
sessions and revoke stored website sessions after commit. Addresses come
from the game session or HTTP `REMOTE_ADDR`, never an untrusted client header.
Guests browse the website anonymously; there is no guest login bridge.

Add `CmdApply`, `CmdAdmissions`, `CmdSoftban`, `CmdMute`, `CmdNotes` and the
audited `CmdBan`/`CmdUnban` to the character cmdset. Add `CmdReferral` and
`CmdAccountPage` to the account cmdset, even when Social supplies character
pages. Explicitly allow `CmdApply` in the host's restricted guest cmdset.
With Social, set `SOCIAL_IGNORE_MUTE_ALIAS = False` so its personal filtering
alias does not replace the staff `+mute` command. Personal filtering uses `+ignore`.

Use `CommunicationCharacterMixin` from `evennia_links.communication` before
`DefaultCharacter` for stock say/whisper and direct speech. Use
`CommunicationChannelMixin` before `DefaultChannel` on every channel typeclass.
RPTracker 0.2.3's `ICChannel` already includes it. Preserve other documented
mixin order; see the reference game's typeclasses. Call
`evennia_moderation.scripts.ensure_retention_sweep()` on server start/reload
to create one persistent daily maintenance Script.

## Applications and review

Add a form to the host's existing `JOBS_REQUEST_FORMS` registry:

```python
JOBS_REQUEST_FORMS["admission"] = {
    "label": "Player application",
    "owner": "moderation",
    "outcomes": ["approved", "declined"],
    "questions": [
        {"key": "introduction", "label": "What brings you to the game?"},
        {"key": "conduct", "label": "Do you agree to the conduct policy?",
         "type": "boolean"},
    ],
}
MODERATION_APPLICATION_FORM = "admission"
```

`+apply` checks intake and throttles the address before asking questions. The
password is hashed when entered and never put in Jobs' text or saved answers.
Submission atomically rechecks intake, reserves the case-insensitive account
name and seat, and claims the referral code. Changed questionnaire wording
requires restarting. Address throttles use short-lived keyed digests.

Staff review through `+jobs/form admission`, ordinary Jobs decisions and web
review pages, or `+admissions`. Only approve/decline are allowed. Staff review
context includes the account name, referrer, address and re-application checks;
it never includes credentials. Addresses matching existing bans and previous
declined/lapsed applications are advisory checks, not automatic declines.

Approval creates an account from the existing hash, records its referral and
deletes the pending application and address. `account_admitted` supplies
`account`, `submission` and `referral` inside the transaction. Receivers must
use `submission.pk` for idempotency and `on_commit()` for external effects.
A receiver failure rolls back the account, referral and review decision.
Game-specific starting rewards belong in the host's integration.

Decline/expiry erase the hash, release the name and allowance, and invalidate
the code. Referrers are notified online or at their next login. Reasons stay
private unless staff select the web checkbox or use
`+admissions/declineshare <job>=<reason>`.

Hosts requiring reviewed admission must disable ordinary signup on both
telnet and the direct website registration endpoint. The public reference
game deliberately retains ordinary signup as a separate demonstration.

## Runtime settings

Each setting below has a validated `+runtime` override:

| Setting | Default | Meaning |
|---|---|---|
| `MODERATION_PLAYER_CAP` | `None` | Approved accounts plus pending seats; no cap by default |
| `MODERATION_REFERRAL_MODE` | `"optional"` | `off`, `optional`, or `required` |
| `MODERATION_REFERRAL_ALLOWANCE` | `0` | Game-wide invitations per account and period |
| `MODERATION_CODE_DAYS` | `14` | Unused code lifetime |
| `MODERATION_APPLICATION_DAYS` | `14` | Pending application lifetime |
| `MODERATION_INTAKE_CLOSED` | `False` | Stop new applications |
| `MODERATION_CLOSED_MESSAGE` | `"Applications are currently closed."` | Explicit closure message |
| `MODERATION_SOFTBAN_HOURS` | `48` | Default timed ban |
| `MODERATION_STAFF_LOCK` | `"cmd:perm(Builder)"` | Moderation command/service authority |

Pending reservations remain valid if intake closes or the cap drops. Guests,
current staff accounts and manually retired seats are excluded. Retirement
leaves the account usable and is reversible. There is no automated retirement
or per-account allowance adjustment. `MODERATION_STAFF_PERMISSION` defaults
to `Builder` for account-level counting and staff page recipients; quelling
does not change that status. Align it and Jobs' authority with host policy.

`+referral` issues a random single-use code; `/list` shows only the caller's
codes and allowance, shared by all alts. Approved referrals consume allowance
permanently within their accounting period; live unused codes and pending
reservations also consume it. A reserved code follows the application's
deadline rather than its old unused-code expiry. Declines and lapses return
allowance without reactivating the code. Staff get the same allowance.

`+admissions/tree <account>` shows the staff-only referral tree.
`/backfill <account>=<referrer>` records manually admitted players and refuses
cycles or conflicting parents. `/reset` starts a new allowance period without
deleting history; decide pending applications first. Unused old codes are
invalidated. Referrer deletion preserves pending reviews and name snapshots.
There is no waitlist.

## Moderation

```text
ban <target>=<reason>
ban/ip <address>=<reason>
unban <number>
+softban <account>=<reason>
+softban/ip <address or CIDR>=<reason>
+softban/duration <account>=<hours>
+softban/lift <account>
+softban/liftip <address or CIDR>
+mute <account>=<reason>
+mute/duration <account>=<hours>
+mute/lift <account>
+notes <account or unambiguous character>[=<private note>]
+notes/actions
+admissions/retire <account>
+admissions/restore <account>
```

The staff commands (`+softban`, `+mute`, `+notes`, `+admissions`) match and
appear in `help` only for callers passing `MODERATION_STAFF_LOCK`, read at
each use. Apply a restriction with a reason before changing its duration. A mute with
no duration remains until lifted. Timed IP bans support IPv4, IPv6 and CIDR.
Stock `ban`/`unban` keep their existing permissions, confirmation prompts and
wildcard matching. The wrappers record actual changes, reasons and lifts.
Direct `ServerConfig` edits are outside that command audit boundary.

All alts share restrictions. Mutes block player pages, all channels, board
posts/replies/edits, explicit OOC chat and speech/posing in OOC rooms. Staff
requests, pages to staff and IC posing remain available. Updated NPC and
Party contribs honor the same policy. Blocked commands explain the expiry
and staff contact routes. Use a timed ban when IC participation must stop too.

Custom communication routes should call
`evennia_links.communication.require_communication(actor, kind, target)`
before creating or delivering content. Kinds: `page` (recipient target),
`channel`, `board`, `room` (optional destination room), and explicit `ooc`.
Any denial wins; receiver errors fail closed. Built-in routes require
Social >=0.7.4, Posing >=0.1.2, Boards >=0.5.3, RPTracker >=0.2.3, and, when
present, NPCs >=0.1.2 and Party >=0.2.2. None is a hard Moderation dependency.

## Guide pages

The `guides/` directory holds pages for
[evennia-guides](../../utils/evennia_guides/README.md): a player page,
`joining`, on applying, referrals, restrictions and what staff can see, and a
staff page, `moderation-staff`. They describe the system in general terms,
without exact numbers, and link only to pages this contrib or its required
dependencies ship. With evennia-guides installed they appear on its web guide;
without it they're ignored. To restate one for your game, add a page with the
same key to `GUIDES_DIRS`.

## Retention and verification

Approved application addresses are deleted immediately. Declined/lapsed
application addresses are purged 90 days after decision. An action's address
remains while active and for 90 days after expiry or early lift. History and
private notes remain after address purging. Expiry is immediate and never
depends on the daily sweep. Server log rotation is separate hosting policy.

There is no public referral tree, staff-note endpoint or address API. Player
alts stay private. Social's separate `SOCIAL_STAFF_RUN_MARKER` option labels
staff-run characters without identifying their accounts or linking their alts.

The package suite covers lifecycle, rollback, permissions and retention.
`test_concurrency` additionally runs against file-backed SQLite for competing
seat/code reservations, allowance issuance and decisions. Reference-game
seams exercise real communications, authentication and rendered review pages.
