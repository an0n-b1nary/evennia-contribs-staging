# evennia-building

Version 0.2.0 supplies individually owned, reviewed interiors. Players draft
isolated rooms, submit immutable revisions, withdraw to edit, and receive an
atomic staff approval. Homes begin unlocked; maps remain private. Apartments
have explicit parent-owner consent and durable shared passage. Staff can
archive/restore property and review quiet flags without automatic reclamation.

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

Migrate before use. Register `CmdBuild` in the character command set. Compose
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
door to its parent and the entrance retains `outside`.

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
workflow. Frontier creation remains unavailable.

Room `build_policy` tags override active primary-region `RegionBuildPolicy`
defaults, then `BUILDING_DEFAULT_POLICY` (`open`). Policies are `open`,
`residential`, `commercial`, `closed`. Closed blocks approval. Purpose mismatches
warn. Links runtime controls default to 2 open projects, 15 total draft rooms,
6 attachment doors (warning, optionally hard) and the reveal switch off.

Use `policy.set_policy(actor, room, policy)` or `+build/policy` for audited
staff changes; `/policy/region` manages region defaults. Drafts deny generic
describe/configure actions: Building services alone version their content and
preserve isolation. Live descriptions use `edit_property_room` or
`+build/property/desc <room>=<text>` and are audited.

Environment inherits the anchor's terrain and active primary region at
promotion, without copying its teleport or control permissions. To request a
different environment use `request_environment` or
`+build/environment <project>={"terrain": ["urban"], "region": 12}`.
Omit a key to inherit it, or submit `{}` to reset the request. The request is
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
decision. Use the unique `property.promotion_id` for idempotent later shop
reconciliation. `property_changed` runs after commit for cache invalidation;
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
via `+build/quiet`, the Building page and inspection-only admin, even without Jobs.

Schedule automatic checks with a persistent global script:

```python
GLOBAL_SCRIPTS = {
    **GLOBAL_SCRIPTS,
    "building_quiet_review": {"typeclass": "evennia_building.scripts.QuietReview"},
}
```

Upgrading 0.1 preserves migrations, objects, ownership, reviews and snapshots.
Existing top-level pending submissions keep their fingerprint. New apartment
proposals require consent; an old self-owned internal proposal must be withdrawn
and resubmitted with its passage receipt before approval.
