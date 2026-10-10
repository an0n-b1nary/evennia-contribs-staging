# evennia-npcs

Player-authored NPCs for Evennia 6.x. Preview release 0.1.0.

Templates are open to play and allow many simultaneous instances. Unique NPCs
have one active instance, an owner, and explicitly shared players. Both spawn
real characters with ruleset-validated stat blocks. No combat package is required.

## Install

Install `evennia-links` and `evennia-rp-rules` first, then this package. Add
`evennia_npcs` to `INSTALLED_APPS` after them and run `evennia migrate --noinput`.
Add `evennia_npcs.commands.NPCCmdSet` **after** your pose/say/emit/semipose and
contest commands so its replacements win. They preserve ordinary PC commands
until you choose `+npc/puppet`. With evennia-posing installed they retain its PC
recording pipeline. Otherwise standard Evennia pose and say remain available.

```python
# settings.py
NPCS_REVEALED = True                 # default False: deploy dark
NPCS_FROZEN = False                  # release/despawn always remain available
NPCS_COMBAT_PROFILES_REVEALED = False # separate future combat rollout

# commands/default_cmdsets.py, at the end of CharacterCmdSet.at_cmdset_creation
from evennia_npcs.commands import NPCCmdSet
self.add(NPCCmdSet)

# commands/default_cmdsets.py, AccountCmdSet.at_cmdset_creation
from evennia_npcs.commands import NPCAccountCmdSet
self.add(NPCAccountCmdSet)

# server/conf/at_server_startstop.py, in at_server_start
from evennia_npcs.scripts import ensure_npc_script_running
ensure_npc_script_running()
```

The three rollout settings are persisted through evennia-links' `+runtime`.
Staff may inspect and prepare hidden NPCs; freezing stops writes and portrayal
for everyone. Runtime changes take effect without a restart.

The default `NPCCharacter` works independently. To use a host character, put
`NPCCharacterMixin` **before** the host class and set `NPCS_TYPECLASS`:

```python
from evennia_npcs.typeclasses import NPCCharacterMixin
from typeclasses.characters import Character

class NPC(NPCCharacterMixin, Character):
    pass

NPCS_TYPECLASS = "typeclasses.npcs.NPC"
```

NPC login hooks deliberately skip PC login rewards and summaries. NPCs carry
`npc` in tag category `npc_system`; evennia-rptracker excludes that marker from
both session owners and partners. NPC portrayal emits its own signal instead
of sending the player's PC through reward or chargen-lock hooks.

## Play

```
+npc/create Market porter=template
+npc/desc Market porter=A porter with a weathered satchel.
+npc/stats Market porter=might:adept,presence:novice
+npc/spawn Market porter
+npc/puppet #123
pose offers to carry the parcel.
say Where should I take it?
+test might
+npc/unpuppet
+npc/despawn #123
```

Use your host ruleset's stat keys and ratings; the example uses rp-rules'
default ruleset. Output identifies `Market porter (NPC, played by YourName)`.
`emit` is attributed too. Virtual portrayal persists across reloads; every
action rechecks permission, location and rollout policy. It cannot execute
arbitrary commands through the NPC. Release portrayal to manage challenges.

`+npc/permit`, `/revoke`, `/transfer`, `/request`, `/requests`, `/approve` and
`/deny` manage sharing. Owners and staff edit and transfer NPCs; shared players
may portray them, not change their definitions. Revoking a player immediately
releases their portrayal. Template definitions still have an owner.

A request to a unique NPC's sole owner auto-approves after 60 days without
playing it, measured from the permission grant if never played. It grants play
access, never ownership. Deleted owners require staff recovery. Set
`NPCS_IDLE_OWNER_DAYS = None` to disable automatic approval. Requests and their
resolutions remain auditable.

Spawns expire after 24 hours without NPC portrayal or live spawner activity.
`NPCS_SPAWN_IDLE_SECONDS = None` disables expiry. The maintenance Script handles
expiry across reloads. Archiving despawns active instances and retains history.

## Optional partners

Use evennia-rp-contest 0.1.1 or later for attributed checks, and evennia-plots
0.3.3 or later for NPC creative-content contributions. The optional extras
declare these minimum versions.

Scenes capture attributed NPC text through a gated listener. `NPCSceneAppearance`
stores scene integer references independently of the spawned object's lifetime:
despawning preserves history. History resolves titles against current scene
privacy; no private text or title is cached. Deleting a scene removes its links.

`+npc/plot Name=#thread` checks both NPC play permission and the real thread's
link policy. `PlotNPCLink` is owned here and uses an integer thread reference.
The plots content collector counts linked NPCs as creative content, sharing
the existing one-point checklist item with IC posts rather than adding a new
bonus. Removing plots disables linking; deleting a thread removes its links.

`+test` uses the NPC's live stat source without creating a chargen sheet. Ability
identifiers are stored for host providers; they do not silently grant PC catalog
effects. No combat, party, scene, plot, posing or tracker model is required here.
There is no NPC web or REST surface in 0.1.

## Full puppeting and combat profiles

`NPCS_ALLOW_FULL_PUPPET = True` enables `/fullpuppet`. It verifies the current
session and character permission, then uses a single-use, session-bound memory
token. Direct `@ic` access stays blocked. `/unfullpuppet`, revocation, despawn
and expiry return the session to its original character when available, or OOC
if the original character was deleted. The return path works while hidden/frozen.
The account command set also preserves the real login character after a refused
`@ic` attempt; Evennia's stock command can otherwise remember the refused NPC.

Every blueprint gets an `NPCCombatProfile`, initially empty and dark. Reveal
profile editing separately with `NPCS_COMBAT_PROFILES_REVEALED`:

```
+npc/profile Market porter={"target_policy":"random","action_weights":{"standard":3,"special":1},"special_moves":[],"reaction_policy":{},"boss_check_schedule":[2,4]}
```

These are durable provider identifiers and weights, not a combat engine. Combat
owns action resolution, affordability, reaction interpretation and manual
Auto-Act invocation. No attacks or timed actions run in this package.

Additional settings: `NPCS_STAFF_LOCK` (default `cmd:perm(Builder)`),
`NPCS_MAINTENANCE_INTERVAL` (300 seconds), `NPCS_SCENES_APP_LABEL` and
`NPCS_PLOTS_APP_LABEL` (defaults `evennia_scenes`, `evennia_plots`).

## Validation

From an initialized, migrated disposable game with this app installed:
`evennia test --settings settings.py evennia_npcs < /dev/null`.
The repository's NPC partner gate also verifies real host seams with optional
partners physically absent; see CONTRIBUTING.md.
