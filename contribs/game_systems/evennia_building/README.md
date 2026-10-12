# evennia-building

Version 0.1.0 supplies individually owned, reviewed interiors. Players draft
isolated rooms, submit immutable revisions, withdraw to edit, and receive an
atomic staff approval. Homes begin unlocked; maps remain private. Apartment
consent, archival and quiet-property flags are reserved for a later release.

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
another owner's consent. Attaching inside another character's property and
frontier creation are explicitly unavailable in this release.

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
ready for future separate apartment boundaries. Deleted owners/anchors deny
access pending staff repair; audit records preserve character names and IDs.

See [the player guide](guides/building.md) and `services.py` for the shared API.
