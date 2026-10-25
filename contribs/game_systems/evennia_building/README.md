# evennia-building

Version 0.5.0 supplies reviewed private homes, public frontier and mixed
settlements. Shared authors draft together under the lead's quotas; every
contributor acknowledges the exact candidate and content reuse terms. Each
proposed home owner accepts their own boundary. Staff approve the entire frozen
project atomically. Public streets have stewards, individual homes have owners,
and neither role gives general Builder powers.

Install `evennia-links` first, then `pip install -e contribs/game_systems/evennia_building`.
Only Links and Evennia are hard dependencies. Maps, Regions, Jobs, Economy and
Social are optional. Building never imports Crafting. A shop purpose records a
proposal; selling requires a separately installed shop integration.

```python
INSTALLED_APPS += ["evennia_building"]
LINKS_ROOM_PERMISSION = "evennia_building.access.room_permission"
LINKS_ROOM_OWNER = "evennia_building.access.owner_of"
LOCK_FUNC_MODULES = (*LOCK_FUNC_MODULES, "evennia_building.lockfuncs")
BUILDING_REVEALED = False
BUILDING_SAFE_ROOM = "#2"
```

Migrate before use. Register `CmdBuild`, `CmdCollab`, `CmdProperty`, `CmdConsent`,
`CmdPassage`, `CmdFrontier` and staff-only `CmdBuildAdmin` in the character command set. Compose
`BuildingRoomMixin` before DefaultRoom and `BuildingExitMixin` before DefaultExit
in the host typeclasses. Keep cooperative `super()` calls. The room mixin guards
managed-room deletion; the exit mixin rechecks access at traversal. Entry locks
work even without mixins, while outward exits remain unrestricted. Integrations
must check `can_teleport(actor, room)` for teleportation: its `None` result means
apply the caller's existing rules, and `False` denies. Social uses the generic
Links travel provider configured below.

```python
LINKS_ROOM_TRAVEL = "evennia_building.access.can_teleport"
LINKS_ROOM_VISIBILITY = "evennia_building.visibility.room_visibility"
# Optional Social >=0.7.2: temporary mood only, without configure rights.
SOCIAL_ROOM_MOOD_PERMISSION = "evennia_building.access.steward_mood_permission"
```

The host owns Maps/Regions visibility. Consult Building first and preserve
existing host rules for unmanaged rooms:

```python
from evennia_building.visibility import room_visibility

def room_visible(room, viewer=None):
    managed = room_visibility(room, viewer)
    if managed is not None:
        return managed
    return existing_host_visibility(room, viewer)

MAPS_ROOM_VISIBILITY = "mygame.visibility.room_visible"
REGIONS_ROOM_VISIBILITY = MAPS_ROOM_VISIBILITY
```

Let callback errors propagate to the consumers' fail-closed boundary. Never use
unlocked physical entry as permission to publish a floor plan. Room overrides
restrict residents and guests; ownership remains authoritative. Residents get
no editing rights and install only with explicit permission. Invitations require
acceptance and specify entry and map scopes. Account alts inherit no grants.
Revocation never ejects occupants; each generated inner room retains an outward
door to its parent and the departure retains `out`, `o` and `outside` as aliases.

With Jobs installed, add its domain-owned form after your host registry:

```python
from evennia_building.request_form import FORM, FORM_KEY
JOBS_REQUEST_FORMS = {**JOBS_REQUEST_FORMS, FORM_KEY: FORM}
```

Settings load before app setup: import the form constants from
`evennia_building.request_form` (which has no model imports), as the sandbox does.
Jobs answers are only a summary, fingerprint and snapshot URL; Building retains
the authoritative room descriptions. Generic Jobs entry points refuse this
form. Withdrawal leaves the active queue; changes requested permits revision;
decline requires a new linked ticket. Removing Jobs leaves Building's native
queue and histories intact. Review and promotion use the same services.

The content reuse wording/version belong to host settings:
`BUILDING_REUSE_ACKNOWLEDGEMENT` and `BUILDING_REUSE_VERSION`. Each submission
records the exact acknowledgement and actor; acknowledgements do not grant
another owner's consent. Apartment attachment uses a separate owner consent
workflow; shared frontier projects use per-candidate agreements (below).

Room `build_policy` tags override active primary-region `RegionBuildPolicy`
defaults, then `BUILDING_DEFAULT_POLICY` (`open`). Policies are `open`,
`residential`, `commercial`, `closed`. Closed blocks approval. Purpose mismatches
warn. Links runtime controls default to 2 open projects, 15 total draft rooms,
6 attachment doors (warning, optionally hard) and the reveal switch off.

Use `policy.set_policy(actor, room, policy)` or `+buildadmin/policy` for audited
staff changes; `+buildadmin/region` manages region defaults. Drafts deny generic
describe/configure actions: Building services alone version their content and
preserve isolation. Live descriptions use `edit_property_room` or
`+property/desc <text>` from inside the room and are audited.

Environment inherits the anchor's terrain and active primary region at
promotion, without copying its teleport or control permissions. To request a
different environment use `request_environment` or
`+build/terrain urban` and `+build/region <region>` from inside the draft.
Use `+build/inherit terrain` or `+build/inherit region` to restore that field's inheritance. The request is
frozen in the exact submission. Staff must explicitly approve that revision
with `approve_environment` or `/environment/approve` before ordinary review
can promote it, including review through Jobs. Removed/archived requested
regions invalidate approval. `BUILDING_STAFF_ONLY_TERRAINS` lists terrain tags
where player attachment is forbidden, even if a proposal requests other terrain;
it defaults to empty. Later anchor edits never retune existing interiors.

With `[web]` installed, mount `evennia_building.urls` at `/building/` and
`evennia_building.api.urls` at `/api/v1/building/`. Pages inherit
`website/base.html`, require a selected character, and use CSRF-protected POSTs.
The API is read-only with the same per-room privacy. Add Links' selected-character
middleware as documented by Links. Admin is inspection-only.

`property_promoted` runs inside the transaction with `property`, `submission`
and `actor`. Required listener errors roll back everything, including a Jobs
decision. Use the individual `property.pk` for idempotent later shop
reconciliation. `property_transferring` runs inside a staff transfer, before
the owner changes, with `property`, `actor`, `new_owner` and
`stock_disposition` (`"return"`, `"transfer"` or `None`); listener errors abort
the transfer. `property_changed` runs after commit for cache invalidation;
it is not durable external delivery. Ownership is per room and per property,
including separate apartment boundaries. Deleted owners/anchors deny
access pending staff repair; audit records preserve character names and IDs.

See [the player guide](guides/building.md) and `services.py` for the shared API.

## Apartments and consent

`attach(..., passage=[room_id, ...])` names a route from the parent's entrance
to the apartment attachment. Omit it to use the parent's generated outward tree.
Applicants need existing entry or preview rights to the proposed passage;
requesting consent cannot discover a restricted parent route by guessing IDs.
All route rooms must belong to one live top-level parent, with usable doors in
both directions. Nested apartments and routes crossing another property are
refused. Request consent with `attachments.request_consent`, inspect the exact
candidate and wording, then the current parent owner calls `answer_consent`.
Only that owner may grant/decline/revoke; staff and residents cannot substitute.
Self-owned attachments record their own receipt. Consent freezes names,
descriptions, geometry, owner, anchor, route, policy report and agreement wording.
Editing invalidates outstanding grants. Approval rechecks the candidate and
consumes its receipt into `AttachmentAgreement`; pre-approval revocation blocks
promotion and rolls back a Jobs decision as well.

The parent gives durable passage to the apartment owner, its residents and
accepted guests with entry scope. Parent locks, bedroom overrides, resident
removal and transfer cannot defeat that specific passage. It confers no parent
floor-plan, remote presence, teleport, ownership, editing or installation rights.
An unlocked child alone grants no passage through a locked parent. The child
controls its door and guests. Neither owner can delete an established route.
Only staff may propose/apply replacement passage; both current owners explicitly
acknowledge the exact route and wording through `PassageChange` first.

## Archive, restore and quiet review

`lifecycle.archive(actor, property, reason=..., include_children=False)` detaches
the preserved entrance, hides ordinary access/discovery and returns characters
to safe rooms. Loose/carried belongings and all room/exit/ownership IDs survive.
Active children block parent archival unless staff explicitly archives them
together. Restore the parent first, then each child. `restore` rechecks the live
anchor, policy, door names/limits, actual geometry and passage. Changed owners
since archival require renewed agreement from both current owners; changed
routes require agreed replacement passage. No timeout changes rights.

Quiet review uses character play, never account login. Configure
`BUILDING_ACTIVITY_PROVIDER` as a callable returning an aware datetime or None.
The reference game uses its existing puppet/unpuppet `sandbox_last_seen` hook.
The default reads `building_last_played`: compose `BuildingCharacterMixin`
before DefaultCharacter with cooperative `super()` to maintain it. Online
characters are active; missing history starts at property creation. The runtime
`BUILDING_QUIET_DAYS` defaults to 35. A persisted first revealed check starts a
minimum reveal grace of the same duration. New activity resolves open flags;
repeated checks deduplicate, and flags grant/revoke no rights. Staff see them
via `+buildadmin/quiet`, the Building page and inspection-only admin, even without Jobs.

Schedule automatic checks with a persistent global script:

```python
GLOBAL_SCRIPTS = {
    **GLOBAL_SCRIPTS,
    "building_quiet_review": {"typeclass": "evennia_building.scripts.QuietReview"},
}
```

Upgrading 0.1 preserves migrations, objects, ownership, reviews and snapshots.
The 0.4 door migration updates stored exit labels, fingerprints and Jobs bindings by identity. New apartment
proposals require consent; an old self-owned internal proposal must be withdrawn
and resubmitted with its passage receipt before approval.

## Shared frontier and mixed settlements

Create a frontier with `services.new_project(actor, name, kind="frontier")`.
The lead chooses a public anchor and a compass direction with `attach`.
`collaboration.invite` and `answer` grant accepted individual collaborators
draft entry, digging and room text editing. Only the lead manages invitations,
attachment, proposed owners, submission, withdrawal and discard. Group membership
grants no rights. All rooms count against the lead's draft quota.

`frontier.add_interior` defines a private home or shop boundary attached by a
named entrance to a proposed public street. Each interior has its own local
coordinates and future owner. `assign_owner` also supports standalone interiors.
Recipients may inspect the exact candidate without entering or editing its draft.
Every active collaborator and every retained contributor must acknowledge the
current candidate hash and reuse wording through `collaboration.acknowledge`.
Every proposed recipient must separately accept ownership. Changes invalidate
receipts; removing a contributor cannot erase their requirement. Agreements may
be revoked until promotion. Consumed receipts and live home ownership survive
membership departure. Existing apartment consent is still required where relevant.

Only explicitly proposed grid connections are promoted. Adjacency is a review
warning and creates no exit. Maps validates placement, direction, stack and
occupied ports/cells; without Maps staff must certify geometry on the exact
submission via `/geometry`. Promotion rechecks actual geometry, access policy,
agreements and door limits inside the same transaction. Frontier inherits terrain
and region; each home remains an independent Property. No group property exists.

Stewards may maintain public room descriptions and temporary moods, and relinquish
stewardship to staff. They cannot lock, admit, install, transfer or configure.
Staff assignment/departure requires the recorded current steward and a reason.
Character inactivity uses the same `BUILDING_ACTIVITY_PROVIDER` and runtime
`BUILDING_QUIET_DAYS` as homes, with reveal grace. It only creates a deduplicated
staff flag in `/quiet`, the staff Building page and admin. No automatic stewardship
or ownership change occurs; Jobs is not needed for this review channel.

`frontier_lifecycle.archive` requires explicit affected frontier/property lists
or replacement public connections. It refuses to strand active homes or break
existing public connectivity. Coordinated retirement preserves identities,
contents, geometry, rights and audit history. Restore the preserved frontier
group before its homes; restoration rechecks policy, ports and geometry.

The web controls are at `/building/projects/<id>/collaboration/` and
`/building/frontier/<id>/`. `/building/frontier/` highlights public growth by
promotion date and plane. The read-only `/api/v1/building/frontier/` exposes public
rooms and stewardship, excluding private interiors and unpublished proposals.
Maps' `frontier` overlay carries public provenance and approval metadata.

Upgrade 0.2 with normal migrations. Historical migrations, ordinary interior
snapshot shape and the stable `building_interior` request form identifier are
preserved; the 0.4 data migration upgrades stored exit references and their fingerprints.

## Fixture consumers

For Crafting >=0.4, also set `LINKS_ROOM_LIVE` to
`evennia_building.access.room_is_live` and `LINKS_ROOM_LOCK` to
`evennia_building.access.lock_room_state`. Archived/draft rooms suspend room
effects. The transaction provider locks the property/frontier state before
consumer object locks, sharing transfer/archive/access-edit serialization.
`access.owner_of(room, include_inactive=True)` identifies archived owners for
fixture recovery; the default lookup still excludes archived rooms. Building
awards no furnishing credit itself: Crafting owns that collector.
`LINKS_OWNED_ROOMS = "evennia_building.access.owned_room_ids"` supplies live
owned room ids in one query, so furnishing credit does not scan the whole grid.

## Guide pages

The staff-only [`building-staff`](guides/building-staff.md) page covers staff tasks, command permissions, safe changes, privacy and review queues. It stays readable by guide staff before player systems are revealed.

The `guides/` directory holds player and staff guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `building` and `building-frontier`. They
explain the system to players in general terms, without exact numbers, and link
only to pages this contrib or its required dependencies ship. With
evennia-guides installed they appear on its web guide; without it they're
ignored. To restate one for your game, add a page with the same key to
`GUIDES_DIRS`.

## Player command break in 0.4

Player Building is split into `+build`, `+collab`, `+property`, `+consent`,
`+passage` and `+frontier`. Draft edits infer the project from the room where
the character stands. Submit, discard, withdrawal and agreement actions preview
the candidate and issue actor-bound, expiring confirmation tokens. Version,
fingerprint, owner and wording checks remain in the transactional services.
The old player forms are refused. Staff operations use `+buildadmin` in 0.5;
old `+build` staff forms are also refused. See the staff guide for the complete
command map. `/approve`, `/changes`, `/decline`, `/environment`, `/geometry`,
`/restore`, `/frontierrestore` and `/apply` preview and print an expiring
confirmation command. Audited reasons follow ` # `.

Transfers, archives, frontier retirements, stewardship and passage proposals
start durable private staff drafts. Set each field separately and use
`+buildadmin/finish` to preview, then repeat its printed confirmation command.
Use `/draft` to inspect or `/cancel` to abandon it. Transfers default to clearing
access grants; `/grants retain` preserves them. Shops require `/stock return`
or `/stock transfer`. Archives require `/children yes` for active apartments.
Frontier plans list additional `/frontiers` and `/properties` separately;
`/replacement <room>/<direction>=<room>` adds one bypass connection.
Tokens bind the actor, draft choices and current affected records; a changed
owner or steward requires restarting the draft. Passage proposal and staff
application never replace the two owners' separate `+passage` agreements.

`+build/dig north=Kitchen` places a neighbouring room with destination-named
doors and direction aliases. Explicit coordinates and custom names use a durable
room plan: `/dig <name>`, `/x`, `/y`, `/floor`, `/doorname`, `/back`, `/finish`.
`/direction` chooses a neighbouring cell and its aliases. `/cancel` drops a plan.
`+build/room <room>` moves between draft spaces, including settlement interiors.

Automatic door names follow their destination's renames; custom names remain
fixed. Entrances gain `in`, and departures are named after the anchor with
`out`, `o`, `outside`. Rename clashes keep the old label and appear in review
warnings. Route and lifecycle checks retain exit IDs, endpoints, aliases and
locks while ignoring automatic label changes. The one-way 0.4 data migration
renames existing defaults and updates stored candidates, agreements, archives
and linked Jobs fingerprints. It preserves object identities and migration
history. Direction aliases and names work without Maps; tagged display belongs
to Maps' optional exit-tag mixin.
