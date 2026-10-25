# evennia-lore

> ⚠️ **Preview status.** This contrib is in the [evennia-contribs-staging](https://github.com/an0n-b1nary/evennia-contribs-staging) pre-upstream channel. APIs may change before submission to `evennia/evennia`.

Wiki-like lore compendium for [Evennia](https://www.evennia.com/) games. Players submit
and discover lore entries (`+lore`), investigate topics (`+investigate`), and passively
acquire entries as they RP. Storytellers share restricted content (`+share`). Staff
affirm entries, keep mysteries sealed, and (optionally) approve submissions.

Every entry has two layers: **IC content** that may be false, because rumors and
legends can be, and an **OOC layer** (accuracy and OOC notes) that never is. See
[Two layers](#two-layers-ic-content-and-the-ooc-layer).

---

## What's included

| Component | Purpose |
|---|---|
| `LoreTag`, `LoreEntry`, `LoreVersion` | Core models |
| `LoreNotice` | OOC notices kept for offline characters, delivered at their next puppet |
| `evennia_lore.layers` | Kinds, accuracy and the rules that keep the OOC layer honest |
| `LoreAcquisition`, `PlotLoreLink`, `LoreSceneLink`, `LoreRegionLink` | Bridge models (integer soft-refs) |
| `select_passive_lore()` | Weighted-random trickle acquisition engine |
| 5 commands | `+lore`, `+investigate`/`+inv`, `+share`, `+hint`, `+forget` |
| Website surface (`[web]`) | 13 views, accessible forms, Bootstrap 4 templates |
| Guide pages (`guides/`) | `lore` and the `ic-may-mislead` principle, for evennia-guides |
| DRF API (`[web]`) | `LoreEntryViewSet`, `LoreTagViewSet` |

---

## Installation

**Core** (models + commands + trickle engine, no web deps):

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_lore&egg=evennia_lore"
```

**With web + API surface:**

```
pip install -e "git+https://github.com/an0n-b1nary/evennia-contribs-staging.git#subdirectory=contribs/game_systems/evennia_lore&egg=evennia_lore[web]"
```

Add to `INSTALLED_APPS` in `server/conf/settings.py`:

```python
INSTALLED_APPS += ["evennia_links", "evennia_lore"]
# For the [web] extra, also add:
INSTALLED_APPS += ["evennia_accessibility"]
```

**Run migrations:**

```
evennia migrate evennia_lore
```

---

## Add commands to your CharacterCmdSet

```python
from evennia_lore.commands import CmdLore, CmdInvestigate, CmdShare, CmdHint, CmdForget

class CharacterCmdSet(CmdSet):
    def at_cmdset_creation(self):
        self.add(CmdLore)
        self.add(CmdInvestigate)
        self.add(CmdShare)
        self.add(CmdHint)
        self.add(CmdForget)
```

---

## Command syntax

Write a new entry with `+lore/submit <title>`, save the editor, then set
`+lore/kind <id>=<kind>` and `+lore/scene <id>=<scene#>` as needed. Authors
can configure their own submissions before staff approval. Changing a kind
preserves accuracy; use `/accuracy <id>=open` for an undecided rumor.
`+lore/plot <id>=<plot#>` links a plot, and staff use
`+lore/major <id>=<tag>` for major tags.

Share held, published lore with `+share <id>=<character>`. Each command takes
at most one switch; unique switch prefixes and mixed case are accepted.

## Settings

| Setting | Default | Description |
|---|---|---|
| `LORE_STAFF_LOCK` | `"cmd:perm(Builder)"` | Staff lock for approve/reject/unflag/share operations; HTTP checks use the shared web policy |
| `LORE_REQUIRE_APPROVAL` | `False` | When True, submissions start as SUBMITTED (awaiting staff review) instead of PUBLISHED. Separate from affirmation |
| `LORE_KINDS` | `{"fact": "Fact", "rumor": "Rumor", "legend": "Legend"}` | Kind keys and labels. Keys are stored on entries; keep them stable |
| `LORE_ACCURATE_KINDS` | `("fact",)` | Kinds whose IC content is always accurate |
| `LORE_DEFAULT_KIND` | `"fact"` | Kind for entries that don't name one |
| `LORE_STAFF_REVIEW_HOOK` | `None` | Dotted path to `callable(title, description)`, e.g. `evennia_jobs.integrations.staff_review.file_review_job`. Receives affirmation requests and sealed-lore reminders from player-concluded threads |
| `LORE_PASSIVE_WEEKLY_CEILING` | `5` | Max passive acquisitions per character per week |
| `LORE_PASSIVE_LEAN_MULTIPLIER` | `Decimal("2.0")` | Weight multiplier for lean-matching entries |
| `LORE_SESSION_CONTEXT_PROVIDER` | `None` | Dotted path to a session context provider: the shipped one or your own (see below) |
| `LORE_RPTRACKER_APP_LABEL` | `"evennia_rptracker"` | App label for the rptracker contrib |
| `LORE_SCENES_APP_LABEL` | `"evennia_scenes"` | App label for scenes (used for scene links + hint regions) |
| `LORE_PLOTS_APP_LABEL` | `"evennia_plots"` | App label for plots (used for plot-lore links and lean) |
| `LORE_REGIONS_APP_LABEL` | `"evennia_regions"` | App label for regions (used for region weighting and hint) |
| `LORE_MAP_LOCKED_NOTE` | `"not yet known: learned through roleplay"` | The note beside a public entry the viewer's character hasn't learned, in the map's room panel |

The staff website's **Lore Review** page always lists affirmation requests. Its
publication-approval section appears only when `LORE_REQUIRE_APPROVAL` is true.
Turning approval off hides older submissions from this page without publishing,
rejecting or deleting them; turning it back on restores their review queue.
| `LORE_MAP_ENTRY_URL_NAME` | `"lore-detail"` | Route the room panel links known entries to; `""` for no links |

---

## Two layers: IC content and the OOC layer

The IC layer may mislead characters; the OOC layer never misleads players.

| Field | Layer | Notes |
|---|---|---|
| `body` | IC | What characters know, read and repeat. May be false. |
| `kind` | — | How the world treats it: Fact, Rumor, Legend (`LORE_KINDS`). |
| `accuracy` | OOC | `accurate`, `inaccurate`, `partly` or `open`. |
| `ooc_notes` | OOC | Where a story came from, what's actually true. Never false. |
| `sealed_notes` | OOC, staff only | Truths staff keep until the story settles them. |

Rules (`layers.validate`, applied by commands, web forms, the admin and `create_entry`):

- a Fact (any kind in `LORE_ACCURATE_KINDS`) is always `accurate`;
- `inaccurate` and `partly` need OOC notes saying what's true;
- sealed notes need `open` accuracy, which is true for everyone who can't see them.

A new Rumor or Legend starts `open`, so an author who never says whether it's true
isn't recorded as saying it is. The OOC layer follows the body's privacy: a
restricted entry hides both until acquired.

### Affirmation

Affirmation is a visible staff mark that an entry is canon **as described**, OOC
layer included. It never makes a rumor's claim true. It is separate from
publication (`LORE_REQUIRE_APPROVAL`).

| State | Shown to |
|---|---|
| `none` | nobody (no badge) |
| `requested` | everyone: "Affirmation requested" |
| `affirmed` | everyone: "Affirmed by staff" |
| `declined` | the author and staff only, with the staff note |

Affirmation stores a digest of the title, summary, body, kind, accuracy and OOC
notes. Any later change reads "Affirmed by staff, edited since" until staff affirm
again. `affirmed_version` records the highest body version at the time, so
`+lore/diff <id>=<affirmed_version + 1>` shows the affirmed body after an edit.

### Sealed notes and notices

Staff seal notes with `+lore/seal` and publish them with `+lore/unseal <id>=<accuracy>`,
which appends them to the OOC notes and settles the accuracy in one step. Unsealing
is never automatic. Every holder is told: at once if they're in the game, otherwise
at their next puppet (a `LoreNotice`, delivered through Evennia's
`SIGNAL_OBJECT_POST_PUPPET`, with no typeclass wiring). Authors are told the same
way when staff affirm or decline.

When a plot concludes with linked lore still sealed, whoever concluded it
(evennia-plots 0.4.0 sends `concluded_by`; older versions fall back to the thread's
creator) is reminded. If that person isn't lore staff, the reminder also goes to
`LORE_STAFF_REVIEW_HOOK`.

### Signals

`lore_affirmation_changed(entry, state, by)` and `lore_unsealed(entry, by)` join
`lore_entry_created`, `lore_entry_published`, `lore_entry_edited` and `lore_acquired`.

---

## Passive lore trickle

The `select_passive_lore(character, session)` function is called at RPSession end (when
rptracker is installed). It builds a weighted pool of eligible entries and picks one
proportionally:

| Signal | Weight |
|---|---|
| Linked to an active plot (via PlotLoreLink) | 8 |
| Room directly tagged on entry | 5 |
| Region linked (via LoreRegionLink) | 3 |
| Major tag match | 2 |
| Any tag match | 1 |

An entry with weight 0 is excluded. The lean multiplier doubles the weight for entries
matching the character's `+investigate` lean.

Commands and the web lean form store the preference in the character's persistent
Evennia Attributes, `character.db.lore_lean_type` and `character.db.lore_lean_value`.
No typeclass mixin is required. A character without these Attributes has no lean;
setting or clearing one survives cache eviction and server restarts. Preferences
set before 0.10.3 were only in memory and must be set again after upgrading.

### Session context provider

Cross-domain context (room_id / region_id / thread_ids for a session) is supplied by a
callable you register at `LORE_SESSION_CONTEXT_PROVIDER`. Without a provider the engine
still works, degrading to tag-only weighting.

**Provider contract:**

```python
def get_session_context(session) -> dict:
    """
    Returns:
        {
            "room_id": int | None,   # ObjectDB pk of the session's room
            "region_id": int | None, # Region pk containing the room
            "thread_ids": set[int],  # PlotThread pks active during the session
        }
    """
```

**Shipped provider.** If your game uses the sibling contribs, point the setting at the
one this contrib ships:

```python
# settings.py
LORE_SESSION_CONTEXT_PROVIDER = "evennia_lore.integrations.session_context.get_session_context"
```

| Key | Source | Without the partner |
|---|---|---|
| `room_id` | the session's room | (always available) |
| `region_id` | `RegionMembership.primary_for(room)` from `LORE_REGIONS_APP_LABEL` | `None` |
| `thread_ids` | the session's scene links (evennia-rptracker), then `ScenePlotLink` from `LORE_PLOTS_APP_LABEL` | empty set |

Partners are found through the app registry, so nothing is imported from one that
isn't installed. If one lookup fails, it is logged and the other keys are still returned.

**Your own provider.** Any callable with the contract above works. Write one when room,
region or story context comes from somewhere else in your game:

```python
# my_game/lore_provider.py
def get_session_context(session):
    return {
        "room_id": session.room_id,
        "region_id": my_region_for(session.room_id),
        "thread_ids": my_threads_for(session),
    }

# settings.py
LORE_SESSION_CONTEXT_PROVIDER = "my_game.lore_provider.get_session_context"
```

---

## Soft-partner matrix

The trickle and bridge cleanup register only when the partner app is present:

| Partner app | When present | Effect when absent |
|---|---|---|
| `LORE_RPTRACKER_APP_LABEL` | Register `rp_session_ended` listener (trickle fires) | Trickle dormant; model/API still ship |
| `LORE_SCENES_APP_LABEL` | Register `connect_soft_ref_cleanup` for Scene→LoreSceneLink | LoreSceneLink rows orphaned on hard-delete (rare; harmless) |
| `LORE_PLOTS_APP_LABEL` | Register cleanup for PlotThread→PlotLoreLink; remind whoever concludes a thread of its sealed lore | Same; no reminder |
| `LORE_REGIONS_APP_LABEL` | Register cleanup for Region→LoreRegionLink | Same |
| `LORE_MAPS_APP_LABEL` | Offer the `has_lore` map tile overlay, and the `lore` section of the map's room panel (evennia-maps 0.9+) | No overlay or section; nothing imported |

### The map tile overlay

Install `evennia-maps` (and `evennia-regions`) alongside this contrib and mapped rooms gain a
lore pin. `LoreConfig.ready()` connects `evennia_lore.integrations.maps.provide` to the map's
`collect_tile_overlays` signal, which answers with

```python
{"has_lore": {room_id: True}}
```

in two queries for the whole grid — one to resolve each room's primary region, one to ask
which of those regions have readable lore.

Lore attaches to *regions* and the map draws *rooms*, so this resolves the room→region step
itself through `LORE_REGIONS_APP_LABEL`; with regions absent the overlay is simply empty.
The pin uses the same eligibility as the passive pool — PUBLISHED + PUBLIC + not archived —
**regardless of whether the viewer is staff**. A pin does not name an entry; it says "there
is lore here" on a public page, and widening it for staff would only make the map disagree
with the compendium.

### The room panel's lore section

Clicking a room on the live map opens its panel, and `provide_detail` answers the map's
`collect_tile_detail` signal with a `lore` section for the room's primary region. It's
per viewer, the character the visitor plays on the website:

- **Known entries**, ones the character holds a `LoreAcquisition` for, are listed and linked.
- **Public entries it doesn't know yet** are listed by title, locked, with
  `LORE_MAP_LOCKED_NOTE` beside them. That's the point of the section: it shows a player
  there's lore here they could still pick up through play.
- **Restricted entries it doesn't know** are counted, never titled. Only a storyteller's
  `+share` grants them, so naming one would publish what the restriction holds back.

The summary reads like "4 entries are tied to this region. You know 1." Staff see every
entry listed and linked, restricted ones noted as such. Three queries per click: the
region, its entries, and which of them the viewer knows.


---

## Web surface (requires `[web]`)

```python
from django.urls import include, path
urlpatterns += [path("lore/", include("evennia_lore.urls"))]
```

URL names: `lore-list`, `lore-create`, `lore-compendium`, `lore-queue`, `lore-lean`,
`lore-detail`, `lore-edit`, `lore-history`, `lore-diff`, `lore-approve`, `lore-reject`,
`lore-affirm`, `lore-decline`.

The detail page shows the IC content and the OOC layer as separate labelled
sections. The list filters by `?kind=` and `?affirmation=affirmed|requested`; the
queue lists affirmation requests beside submissions.

---

## REST API (requires `[web]`)

```python
from django.urls import include, path
urlpatterns += [path("api/v1/", include("evennia_lore.api.urls"))]
```

Generates `/api/v1/lore/`, `/api/v1/lore/<id>/`, `/api/v1/lore-tags/`, `/api/v1/lore-tags/<id>/`.

Privacy rules:
- Staff (LORE_STAFF_LOCK) see all non-archived entries.
- Non-staff see only PUBLISHED entries.
- RESTRICTED `body` is `null` unless the caller has a `LoreAcquisition` row; so are
  `accuracy` and `ooc_notes`, which follow the body.
- `affirmation` reads `none` for a declined entry unless the caller is its author or
  staff, and `?affirmation=declined` returns nothing to non-staff.
- `sealed_notes` and the decline note are never in the API.

---

## Programmatic API

### Crafted citations and recognition

Install compatible crafting 0.8 or newer (`pip install evennia-lore[crafting]`)
to enable two optional facets. Lore registers them through crafting's collector
only when both apps are installed. Existing crafting 0.6 continues without the
integration; upgrading lore alone never creates a hard crafting dependency.

Complete an ordinary `+craft` draft, then attach lore before paying:

```
+lorecraft/cite 2 = #14
+lorecraft/cite = #20
+lorecraft/recognise #14=A familiar sign is woven into the hem.
+craft
+craft/resources 3 timber
+craft/finish
```

Recognition addresses the entry first: `#14` uses the primary contributing niche;
`#14/weaving` charges the contributing weaving niche. The feature text is plain
single-line prose. The former pipe-separated form is refused.

Register `CmdLoreCraft` alongside your other lore commands. `/uncite N` and
`/unrecognise N` remove draft features. A numbered citation applies to that
authored page; an unnumbered citation applies on any successful page read.
The crafter must actually hold the published entry, even if it is public.
Staff may author references to any published entry. Restricted references are
permitted and stay in the immutable CraftRecord for review. A change to the
entry's publication state or the crafter's holdings is rechecked at completion.

Citations are free. Recognition costs one additional input per feature, from
a contributing niche. An optional niche on `/recognise` chooses that contributor;
otherwise the first contributor supplies it. The category defaults to a category
already used by that niche's craft inputs; `LORE_RECOGNITION_CATEGORIES` can map
niche keys to permitted categories. Features are plain single-line text, up to
400 characters each, at most 20 per item. Up to 100 citations may be attached.

Successful `item.read(reader, page=...)` operations acquire cited entries with
source `read`. Existing acquisitions retain their original source. Contents,
previews, provider enumeration, plain full-text dispatch and failed or redacted
reads do not acquire lore. Reading and bookmark writes commit together; a
failed read rolls both back. Reading creates no XP or inspiration links, and is
not subject to the passive weekly ceiling. `+forget` removes the acquisition;
rereading a qualifying page reacquires it. Citations reference the current entry,
not a copied body or frozen truth. Withdrawn/deleted entries stop granting;
sealed notes stay staff-only under the ordinary lore privacy rules.

Recognition appears on deliberate look/inspection only for viewers holding the
entry. Staff see all available features with their gates labelled. Recognition
never grants lore and does not enter object names, room rosters, market keywords
or automatic emissions. An item's mutable Attributes cannot forge either facet.
When lore is removed, metadata remains in craft history while its effects hide;
new crafts requesting those missing facets are refused without spending.

The API adds `facets={"lore_citations": [{"entry": entry.pk, "page": 2}],
"lore_recognition": [{"entry": entry.pk, "text": "..."}]}` to crafting's
`craft_cost` and `craft`. Entry values are internal PKs; commands resolve human
`#entry_number` identifiers. Staff review includes these facets in the record.

**Journal/copy bridge:** this release covers fixed authored books and staff
tomes. Citation-preserving copies and citations on journal revisions remain a
separate integration step. Copies should preserve verified source citations
without requiring the copier to hold them, while copying itself grants nothing.
Journal citations belong to a particular revision, with explicit retain/replace
choices on revision and frozen citation snapshots in editions. Recipe teaching
remains separate. Do not assume text-only copying already carries these facets.
Blank journal drafts reject citations until revision-scoped support is available.

### Staff tomes without crafting

Register `CmdTome` and `CmdReadTome`. Add the latter after any crafting cmdset
to provide a shared `read` command: staff tomes remain readable while crafting
is hidden, and hidden crafted items are still refused. `+lorecraft` remains
hidden until crafting is revealed.
The staff permission uses the existing `LORE_STAFF_LOCK`.
Select a page with `read <item>=<page>`; `read <item>` resumes your bookmark.
Item names ending in numbers remain whole names. Positional page suffixes are refused.

```
+tome/new an old chronicle
+tome/desc A dusty book bound in dark leather.
+tome/page Preface = A traveller's introduction.
+tome/page The Exile = An old account, possibly unreliable.
+tome/cite 2 = #14
+tome
+tome/publish
read an old chronicle=2
```

Tomes have 1-100 fixed pages and at most 12,000 characters including their
titles (up to 80 characters each). This book limit does not limit lore entries.
Each publication creates an append-only `LoreTomeRecord`; changing item
Attributes cannot rewrite its pages or authorize citations. Bookmarks are
personal and keyed to the record, so replacement books do not inherit progress.
Staff create a new tome to publish different text. There is no crafting niche,
resource cost or Workshop requirement. `items.create_tome` exposes the same
validated staff-only operation to builders and seed scripts. Set
`LORE_TOME_TYPECLASS` to a subclass of `items.LoreTome` to add host hooks; put
your stock/deletion guard mixin before it in the MRO.

`+lore/object` and `/unobject` now require both entry-editing rights and control
of the target, unless staff. Object tags remain builder/discovery metadata;
they never supply crafted recognition or overwrite another maker's prose.

```python
from evennia_lore.models import LoreEntry, LoreAcquisition, LoreSceneLink

# Submit a new entry programmatically (author=None for system-generated):
entry = LoreEntry.create_entry(
    title="The Founding",
    author=character,
    body="In the beginning...",
    privacy="public",
    kind="legend",              # accuracy defaults to "open" for non-Fact kinds
    ooc_notes="Told in every camp.",
)

# The OOC layer, affirmation and seals (LoreLayerError on a broken rule):
entry.update_layers(accuracy="partly", ooc_notes="Half of it is true.")
entry.affirm(affirmed_by=staff_character)
entry.update_layers(accuracy="open")
entry.seal("What staff know.")
entry.unseal("accurate", unsealed_by=staff_character)  # returns holders told

# Record an acquisition (storyteller share):
LoreAcquisition.objects.get_or_create(
    entry=entry,
    character=target_char,
    defaults={
        "character_name": target_char.key,
        "source": LoreAcquisition.Source.STORYTELLER,
    },
)

# Link to a scene (scene_id is an integer soft-reference):
LoreSceneLink.objects.get_or_create(entry=entry, scene_id=scene.pk)
```

## Theming

Every colour in this contrib's stylesheet is a shared `--evennia-color-*`
token with its usual colour as the fallback, so the pages look the same
until your game sets one. Set them on `:root` in your own stylesheet to
retheme these pages along with the other contribs'. The token list and an
example are in [evennia-accessibility's README](../../utils/evennia_accessibility/README.md#theme-tokens).

---

## Guide pages

The staff-only [`lore-staff`](guides/lore-staff.md) page covers staff tasks, command permissions, safe changes, privacy and review queues. It stays readable by guide staff before player systems are revealed.

The `guides/` directory holds player and staff guide pages for
[evennia-guides](../../utils/evennia_guides/README.md): `lore` and the
`ic-may-mislead` principle. They explain the system to players in general
terms, without exact numbers, and link only to pages this contrib or its
required dependencies ship. With evennia-guides installed they appear on its
web guide; without it they're ignored. To restate one for your game, add a page
with the same key to `GUIDES_DIRS`.

---

## Version history

See [CHANGELOG.md](CHANGELOG.md).
