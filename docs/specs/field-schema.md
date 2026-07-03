# §17. Field Schema (v1, `.tc`-compatible)

- [x] [#6: decision: tutorial and reference-image field lists](https://github.com/borco/rehuco/issues/6)

The concrete starting field set for rehuco, derived from the fields a real tutcatalog4 (tc4)
`.tc` file carries. §4.1 settles the *scope* of the `.rehu` schema and defers the detail here.

## §17.1 Scope and intent

The first release must **double-click an existing `.tc` and view it**. That goal — not a
speculative ideal schema — fixes the starting field set: rehuco has to accommodate whatever
tc4 actually stored.

- **Ground truth is tc4**, the only predecessor actually used to view and edit `.tc` files.
  Its data model (`Tutorial`) and viewer (`Viewer.qml`) are the reference, not the later
  tc5/resource-hub rewrites (design drafts, never shipped for this purpose).
- **`.tc` is YAML; `.rehu` is JSON** (§4.1). v1 reads `.tc` through an adapter into rehuco's
  model; it does not write `.tc`. No line of the old reader survives verbatim — only its
  field list drives the mapping.
- **View-only defers editing-era calls** (e.g. whether dropped flags resurface as tags), but
  the schema is modeled at its **target shape** where that costs nothing — notably `sources`
  (title + publisher + URL per platform, §17.2.3), which a legacy `.tc` fills as one primary
  entry. The `collections` / `learning_paths` membership fields are modeled too (§17.2.3); only
  the Collection *type*'s field set stays deferred (§17.2.1).

## §17.2 Field mapping: tc4 `.tc` → rehuco

Every key a tc4 `.tc` carries, with its rehuco disposition. "Group" is the common/plugin split
(§4.1, §13) and says **where the field lives on disk**: `common` at the top level, everything
else under the type's plugin block (§17.2.1). The boundary can be refined post-v1 since the
generic editor (§13.4) does not depend on it.

| `.tc` key | tc4 label | rehuco field | type | group | shape | disposition |
| --- | --- | --- | --- | --- | --- | --- |
| `type` | — | *(type selector)* | enum | — | Tutorial / ReferenceImages / Collection | keep — selects resource type / plugin |
| `title` | Title | `sources[].title` | text | common | record + primary¹ | keep — see §17.2.3 |
| `publisher` | Publisher | `sources[].publisher` | text | common | record¹ | keep — see §17.2.3 |
| `url` | Homepage | `sources[].url` | URL | common | record¹ | keep — see §17.2.3 |
| `author` | Authors | `authors` | text list | common | multi | keep, rename to `authors`; stays separate² |
| `released` | Released | `released` | date | common | partial-precision | keep — Y / Y-M / Y-M-D; content publication date |
| — | *(none in tc4)* | `created` | datetime | common | scalar | **new** — record created; seed from file timestamp on import |
| — | *(none in tc4)* | `updated` | datetime | common | scalar | **new** — record last edited; seed from file mtime on import |
| `description` | *(bottom pane)* | `description` | Markdown | common | scalar | keep — embeds sibling `infoXX` images |
| `tags` | Tags | `advertised_tags` | text list | common | multi | keep, rename — web-scraped |
| `extraTags` | Exta Tags *(sic)* | `extra_tags` | text list | common | multi | keep, rename to snake_case — personal edits |
| `original_size` | Original size | `original_size` | size (bytes) | common | scalar | keep — see §17.3; empty for Collection |
| `current_size` | Current size | `current_size` | size (bytes) | common | scalar | keep — see §17.3; empty for Collection |
| `complete` | Complete | `complete` | bool | Tutorial, RefImages | scalar | keep — "all files present"; default `true` |
| `online` | Online | `online` | bool | Tutorial, RefImages | scalar | keep — "source still available online" (§17.2.4) |
| `rating` | Rating | `rating` | rating (int) | Tutorial, RefImages | scalar | keep — **per-user**; may be negative |
| `viewed` | Viewed | `viewed` | bool | Tutorial, RefImages | scalar | keep — **per-user** |
| `todo` | To Do | `todo` | bool | Tutorial, RefImages | scalar | keep — **per-user** |
| `keep` | Keep | `keep` | bool | Tutorial, RefImages | scalar | keep — **per-user** |
| — | *(new)* | `favorite` | bool | Tutorial, RefImages | scalar | **new** — **per-user**; separate UI (§17.2.6) |
| `collection` | Collection | `collections[].title` | text | Tutorial, RefImages | record³ | keep — see §17.2.3 |
| `collection_index` | Index | `collections[].index` | int | Tutorial, RefImages | record³ | keep — see §17.2.3 |
| `learning_paths` | Learning Paths | `learning_paths[].title` (+ `.index`) | record | Tutorial, RefImages | multi, user-defined⁴ | keep — see §17.2.3 |
| `duration` | Duration | `original_duration` (+ `current_duration`, `advertised_duration`) | duration (seconds) | Tutorial | scalar | keep, split — see §17.3 |
| `level` | Level | `level` | multi-choice | Tutorial | multi | keep — beginner / intermediate / advanced / any |
| — | *(none in tc4)* | `images_count` | int | ReferenceImages | scalar | **new** — empty on import (not from `duration`), filled by scanning (§17.6) |

¹ `sources` is a list; each item is `{ title, publisher, url, primary? }`. The item with
`primary: true` (or the first item if none is flagged) is canonical — its **title** is the
display title and the basis for folder/file-name suggestions (§17.2.3).
² **`authors` stays one shared list**, not per-source — a differing author set signals a
*different* tutorial, not another source of the same one (§17.2.3).
³ one **collection membership** = `{ title, index, url? }`; a resource may belong to several
series (§17.2.3).
⁴ **learning paths** are `{ title, index, visibility }`; `visibility` is the UI `public` /
`private` toggle; the owner is implicit by per-user block (§17.2.3).

Values tc4 derives rather than stores (not `.tc` keys): the folder/parent path (from the file
location), canonical folder-name suggestions, and the transient "Computed" duration/size from a
disk scan (which in rehuco feed `current_duration` / `current_size` — see §17.3).

### §17.2.1 Resource types

`type` selects one of three. Fields fall into tiers so "common" means *common to all types*
only:

- **Common core (all types)** — `sources` (title/publisher/url), `authors`, `released`,
  `description`, `advertised_tags`, `extra_tags`, `created`, `updated`, and the measured
  `original_size` / `current_size` pair (§17.3) — the sizes are core-scanner output, wanted by
  every file-backed type; a Collection leaves them empty (it may later fill them from member
  stats — see the Collection bullet below).
- **Resource fields (Tutorial + ReferenceImages)** — `rating`, the boolean flags
  (`complete`, `online`, `viewed`, `todo`, `keep`, `favorite`; §17.2.6), and the `collections` /
  `learning_paths` memberships (§17.2.3). A **Collection** declares none of these.
- **Tutorial only** — `original_duration` / `current_duration` / `advertised_duration` and
  `level`.
- **ReferenceImages only** — `images_count`; declares **no** duration (§17.3), so the value
  that leaked as `720` in tc4 has nowhere to land.
- **Collection** — a series/grouping node; its **`title` is the series name** that members
  reference via `collections[].title`. **Which fields it shows/edits is deferred** until a real
  collection is in hand (§17.6), including whether it carries a recomputed member-stats cache
  (in tc4 the extra fields it held were only such a cache, sparing a descent into member
  subfolders). This is separate from the `collections` membership fields, which are settled
  (§17.2.3).

**On disk:** the common core is top-level; every non-common field is nested under a **plugin
block keyed by `type`** (`tutorial`, `reference_images`), each carrying its own `format_version`
(§4.10, §13.3), so the file already has the plugin shape and won't need restructuring when
plugins land. A block `format_version` of **0 means "no plugin yet"** — the fields live there
but no plugin owns them; the first real plugin bumps it to `1`. Fields shared by Tutorial and
ReferenceImages (`rating`, the boolean flags, `collections`, `learning_paths`)
live inside whichever plugin block the file has. Collection has no block yet. See the §17.7
fixtures.

### §17.2.2 Per-user vs shared

`rating`, the per-user boolean flags (`viewed`, `todo`, `keep`, `favorite`), and **private**
`learning_paths` are **per-user** state, not properties of the resource. v1 is single-user/local
so this is invisible, but the schema must keep them separable from shared fields so the
multi-user model (§7, §4.1's per-user `progress`) does not have to relocate them later. The
shared flags (`complete`, `online`) and a learning path toggled **public** (or curated by the
admin) are propagated swarm state instead (§17.2.3, §17.2.6). For now, with no user management,
per-user keys live **inline** in the plugin block (polluting the current scope); a dedicated
per-user block waits on the swarm/user model (§17.6).

### §17.2.3 Sources (multi title / publisher / URL)

One resource can be published in several places — the same tutorial sold on more than one
platform under slightly different names and links (§4.1). This is modeled as `sources`:

```yaml
sources:
  - { title, publisher, url, primary: true }
  - { title, publisher, url }
```

- `sources` is a **list**; each item binds a `{ title, publisher, url }` for one platform,
  replacing tc4's scalar `title` / `publisher` / `url` (the "Homepage").
- The item flagged **`primary: true`** is canonical (an inline marker, not a positional index).
  Its **title** is the display title and the basis for the folder/file-name suggestion widget
  (§4.1).
- **Resolution is permissive.** Normally exactly one item is flagged. If **none** is, the
  **first item** is primary; if **several** are, the **first** flagged one wins. Neither should
  happen — `.rehu` is not hand-written — but the reader tolerates it rather than erroring.
- **`authors` are not part of a source** — one shared list serves the resource. The same course
  under a slightly different name elsewhere is still the same course; a *different* author set
  means it is probably a *different* tutorial, not another source of this one.
- **Legacy import** — a scalar `title` / `publisher` / `url` becomes a single `sources` entry,
  marked `primary: true`.

Collections and learning paths are **membership lists** (settled — distinct from the Collection
*type*, below). tc4's scalar `collection` + `collection_index` become a list, since a resource
may belong to several series, each with its own order and optional link:

```yaml
collections:
  - { title: "CollectionA", index: 1, url: "xxx" }
  - { title: "CollectionB", index: 10 }
```

- Each entry is `{ title, index, url? }`. `title` is the series name (it matches a
  `type: Collection` record's `title`); `index` is the position within that series; `url`
  optionally links the series' own page. **Publisher-defined.**
- **`learning_paths`** use the `{ title, index, visibility }` shape and render apart from the tag
  fields (a plain tag can't carry an order). **`visibility` is a `public` / `private` toggle in the
  UI**: *private* = only its owner sees it; *public* = shared with the swarm (the admin can also
  curate public ones, §6). The **owner stays implicit** — a personal path lives in that user's
  per-user block (§17.2.2), so we store the **`visibility` flag, not a `user` field**. Public
  paths are propagated swarm state; private ones stay per-user, mirroring `rating` / `viewed` /
  `progress` (§7). v1 is single-user, so the public/private split only bites once there's a
  swarm.
- **Legacy import** — scalar `collection` + `collection_index` become one entry; the flat
  `learning_paths` names become entries with `index` by stored order.

Only the **Collection *type*** stays deferred — which fields a `type: Collection` record
shows/edits, and whether it carries a recomputed member-stats cache (§17.2.1, §17.6). The
membership *fields* above are settled.

### §17.2.4 The `online` flag and local backup

`online` means **the original source is still available online** — not "this is an online-only
resource" (the ambiguity §4.1 warns against). The driving case: many Udemy-style courses are
kept as just a `.rehu` with screenshots plus a pointer to the source (the primary listing's
`url`); the point of the flag is that the course can still be reached at that source.

It is **independent of whether the content is stored locally.** A resource can be
online-and-backed-up, online-but-screenshots-only (no local content), or offline-but-archived.
Local presence is read from `current_size` / `complete`, not from `online`. The tc4 name
**`online` is kept** — with the meaning documented here there is no competing "online-only"
sense to disambiguate against, so the finer `source_online` / `available_online` rename is not
worth it.

### §17.2.5 Record timestamps

`created` and `updated` are **new** full datetime values (not the partial-precision `released`, which
is the *content's* publication date): when the `.rehu` record was first written and last
edited. tc4 stored neither; on import they seed from the file's timestamps. They are shared
record state (an edit that syncs updates `updated`), and relate to the `resource_version` /
timestamp markers used for staleness detection and sync (§4.7).

Once the `versions` list lands in the schema (§7 — v1 carries no versions yet), both become
**derivable**: `created` = the creation entry's date (index 0, which compaction never touches,
§7) and `updated` = the latest entry's date. A later format version may then drop the stored
fields in favor of the derived values — §4.10 makes that migration safe.

### §17.2.6 Boolean flags

For v1 the tc4 boolean flags stay **individual booleans**, as in tc4 — `complete`, `online`
(§17.2.4), `viewed`, `todo`, `keep` — plus a new `favorite`. Import is 1:1 (each tc4 bool maps
to the same-named bool); `favorite`, absent from tc4, defaults to `false`.

- **`favorite` is kept separate**, not lumped with the rest: it carries different semantics (it
  can drive behavior beyond a display flag) and its control may sit in a different place in the
  UI.
- **Scope.** `complete` and `online` are shared/objective; `viewed`, `todo`, `keep`, `favorite`
  are **per-user** (§17.2.2) — inline for now (§17.6).
- **Deferred: a `default_tags` toggle set.** Folding the fixed-vocabulary bools
  (`complete`/`online`/`viewed`/`todo`/`keep`) into one list rendered as UI toggles, with a
  vocabulary from `.rehuco` or defaults, was considered and **deferred** (§17.6): its payoff
  needs the plugin/config system, and §4.10's per-block versioning makes the bool-to-list
  migration safe to do in a later revision. `favorite` would stay separate regardless. `rating`
  never folds in (it is an integer, not a toggle).

## §17.3 Duration and size model

Two orthogonal axes govern both duration and size — **how the value is known** (measured by
scanning files vs claimed by a publisher) and **what it covers** (the complete resource vs
what is still on disk). The second axis exists because the original tracking method was to
**delete files as they were watched**, so "what's left on disk" shrinks over time.

| | measured (scan) | claimed (web) |
| --- | --- | --- |
| **original** (complete resource) | `original_duration`, `original_size` | `advertised_duration` |
| **current** (files still on disk) | `current_duration`, `current_size` | — *(nobody advertises a remaining amount)* |

Fields, and the purpose each serves:

- `original_duration` — measured total of the complete download. Denominator for progress.
- `current_duration` — measured total of files still present; shrinks as watched files are
  deleted. `current_duration ÷ original_duration` ⇒ "how much is left."
- `advertised_duration` — the coarse web claim, kept to verify the download was complete
  (`original_duration` vs `advertised_duration` ⇒ "did I get everything").
- `original_size` — disk footprint when complete. The reference for judging whether an
  alternative source is better or worse: same content across archive schemes stays in the
  same ballpark, so 200 MB stored vs a 500 MB–1 GB candidate reads clearly as higher quality.
- `current_size` — disk currently used by this copy.

There is **no `advertised_size`**: sites publish duration, not tutorial size. The comparison
against an alternative source is done at decision time against `original_size`; the candidate's
size is never stored.

`current_*` describes **this physical copy**, not a person — distinct from the future per-user
`progress` (§4.1). The delete-to-track-progress method does not generalize to the swarm, where
remaining-on-disk (per-node) and watch-progress (per-user) become two different things; the
schema keeps room for a separate `progress` so recording "watched" never again requires
deleting files.

`duration` does not apply to **ReferenceImages** — for that type it is an unknown field, not a
blank one, so it is simply not declared (which is what should have hidden the leaked value in
tc4's shared viewer). The leaked `720` is **not** reinterpreted as `images_count`: on import of
a reference-images `.tc` the old `duration` is dropped and `images_count` is left **empty**,
to be filled later by scanning (§17.6) rather than by guessing it was ever an image count.

### §17.3.1 Canonical unit and the millisecond-leak history

- **Duration is stored as integer seconds.** At tutorial scale (minutes to hundreds of hours)
  sub-second precision is meaningless; milliseconds buy nothing and caused the historical bug.
- **The old bug was ms-vs-seconds, not a `×60` error.** MediaInfo reports track durations in
  **milliseconds**; a single `round(ms / 1000)` is the only conversion to seconds. A build
  that omitted it stored milliseconds — a 1000× inflation — so a legacy catalog can hold a
  **mix** of seconds and stray milliseconds with no marker. Compounding it, precision was lost
  by reconstructing the stored number from the coarse display string.
- **Two rules prevent recurrence:** (a) when scanning, sum in native precision and round to
  seconds **once at the end**, never per file; (b) the formatted string is **output only** —
  editing edits the underlying seconds; the stored number is never re-derived from the display.
- **Legacy `.tc` durations are untrusted.** On import, map the single `duration` into the
  `original_duration` slot (what tc4 displayed) and treat it as advisory until a real scan
  overwrites it. No "if it looks too big, divide by 1000" heuristic — that would corrupt
  genuinely long collections.

### §17.3.2 Human-readable duration format

Carried over verbatim from tc4 (it already matches the desired behavior). For a value `d` in
seconds:

```text
h = d // 3600 ;  m = (d % 3600) // 60 ;  s = d % 60
parts = []
if h:            parts += "{h}h"
if m:            parts += "{m}m"
if s and h == 0: parts += "{s}s"     # seconds are noise once hours are present
render " ".join(parts)               # d == 0 → "" (not "0s")
```

- `2h 15m`, `2h` (minutes zero), `45m`, `45m 30s`, `30s`.
- Hours are **never** rolled into days — large values read as `123h 45m`, not a time of day.

Size renders base-1000 (macOS-Finder style) with two decimals, e.g. `1.50 GB`; `0` renders
empty.

## §17.4 Field types

The distinct value types the viewer must handle:

| type | notes |
| --- | --- |
| text | single line |
| text list | comma-joined for display, deduplicated; `authors`, `advertised_tags`, `extra_tags` |
| url | rendered as an external hyperlink |
| date | **partial precision** — year, year+month, or full date; sorts/compares across mixed precision |
| duration | integer seconds; rendered per §17.3.2 |
| size | integer bytes; rendered base-1000 |
| rating | integer, may be negative; star-style widget |
| bool | yes/no; `complete` shows a warning color when false |
| multi-choice | fixed value set; `level` ∈ {beginner, intermediate, advanced, any} |
| Markdown | rich text; resolves embedded image paths relative to the file's folder |
| int | plain integer; `collection_index`, `images_count` |
| record list | list of small records; `sources`, `collections`, `learning_paths` (§17.2.3) |

## §17.5 tc4 viewer layout (reference for the v1 view)

The exact field order, labels, and widgets from tc4's `Viewer.qml`, as the concrete reference
for the v1 rendering. One shared layout served all types (which is why an inapplicable field
could leak); rehuco instead shows only the fields a type declares.

Field order, in the three groups the layout separates:

- **Header/metadata:** folder-name link → location link → publisher → collection / index
  *(hidden for Collection type or when empty)* → title → authors → released → duration
  *(formatted + Computed/Compute buttons)* → level → homepage *(link)*.
- **State/size:** current size *(formatted + Computed/Compute)* → original size →
  rating *(stars)* → complete *(yes/no, red when false)* → to-do → viewed → keep → online →
  tags → extra tags → learning paths.
- **Description:** Markdown rendered as rich text.

## §17.6 Deferred / open items

- **Common/plugin boundary** — the §17.2 tiers (common core / resource fields / per-type) are a
  first cut; finalize when the field toolkit (A2) and plugin blocks (§13) land. The generic
  editor does not depend on it.
- **Collection *type* — deferred** (§17.2.1) — which fields a `type: Collection` record
  shows/edits, and whether it re-gains a **recomputed** member-stats cache. Decide when a real
  collection is in hand. *(The `collections` membership fields are settled, §17.2.3.)*
- **Membership by identity** — `collections[].title` links to a series by name today; move to
  resource identity (§4.2) once UUIDs are minted.
- **Per-user block** — until user management exists, per-user keys (`rating`, the per-user
  boolean flags, private `learning_paths`) live **inline** in the plugin block; move them to a
  dedicated per-user block with the swarm/user model (§7, §17.2.2).
- **Learning-path visibility storage** — the `public` / `private` toggle (§17.2.3): confirm
  whether a public user path stays in the owner's per-user block (owner implicit) or moves to
  the shared record on toggle. Swarm-era, not v1.
- **`default_tags` consolidation — deferred** (§17.2.6) — a later revision may fold the
  fixed-vocabulary bools (`complete`/`online`/`viewed`/`todo`/`keep`) into one toggle-set list
  with a vocabulary from `.rehuco` (scope, labels/icons), migrated via a plugin-block
  `format_version` bump (§4.10). `favorite` stays separate. v1 keeps individual bools.
- **`images_count` on import** — left **empty** for a reference-images `.tc` (the old `duration`
  is not assumed to be a count); fill later by scanning the sibling `infoXX.*` set or the
  content zip.
- **`created` / `updated` seeding** — confirm which file timestamp seeds `created` on import
  (ctime is unreliable cross-platform; mtime is the safer floor).
- **Description image resolution** — confirm sibling-relative path handling matches §4.6's
  screenshot model.
- **UUID (§4.2) and per-block format version (§4.10, §13.3)** — minted/added when writing
  `.rehu`; not present in legacy `.tc`, so they are an import concern, not a view concern.
- **Partial-date comparison semantics** — `released` stores ISO-prefix strings (`2025`,
  `2025-03`, `2025-03-08`); lexicographic sorting already orders them sensibly, but what a
  comparison or *filter* means for a partial value (treat it as the interval it covers?) is
  not decided — pin down before filtering lands (§17.4).

## §17.7 Example `.rehu` files (validation fixtures)

Concrete `.rehu` documents (JSON, §4.1) that exercise the field set above — usable as
parser/schema validation fixtures.

- **Common core** sits at the top level; everything a type owns is nested under a **plugin block
  keyed by `type`** (`tutorial` / `reference_images`), each with its own `format_version`
  (§4.10, §13.3) — **`0` = no plugin yet**, bumped to `1` by the first real plugin — so the
  layout already matches the future plugin structure. A **Collection** has no block yet
  (deferred, §17.2.1) and carries only common core.
- `sources` is a list; exactly one item carries `primary: true`.
- **Per-user** fields (`rating`, the per-user boolean flags, private `learning_paths`) live
  **inline** in the plugin block for now — without user management a separate per-user block is
  impractical, so they pollute the current scope (§17.2.2, §17.6).
- Values are illustrative; each example stresses the edge case named in its heading.

### Tutorial — multi-source, multi-collection, split duration, year-month date

```json
{
  "format_version": 1,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "Tutorial",
  "created": "2026-01-15T09:30:00Z",
  "updated": "2026-06-20T14:12:00Z",
  "sources": [
    {
      "title": "Intro to Sculpting",
      "publisher": "Example Publisher",
      "url": "https://example.com/intro-sculpting",
      "primary": true
    },
    { "title": "Sculpting, Extended Cut", "publisher": "Second Platform", "url": "https://second.example/sculpting" }
  ],
  "authors": ["First Author", "Second Author"],
  "released": "2025-03",
  "description": "# Intro to Sculpting\n\nCovers the basics; see `info01.jpg` for reference.",
  "advertised_tags": ["sculpting", "3d", "modeling"],
  "extra_tags": ["rework"],
  "original_size": 5368709120,
  "current_size": 1073741824,
  "tutorial": {
    "format_version": 0,
    "collections": [
      { "title": "Sculpting Series", "index": 1, "url": "https://example.com/series" },
      { "title": "Bundle 2025", "index": 10 }
    ],
    "learning_paths": [
      { "title": "My Sculpting Path", "index": 2, "visibility": "private" }
    ],
    "original_duration": 71220,
    "current_duration": 18000,
    "advertised_duration": 72000,
    "level": ["intermediate"],
    "complete": true,
    "online": true,
    "viewed": false,
    "todo": false,
    "keep": false,
    "favorite": true,
    "rating": 4
  }
}
```

### ReferenceImages — empty `images_count`, no duration, full date

```json
{
  "format_version": 1,
  "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "type": "ReferenceImages",
  "created": "2026-02-01T11:00:00Z",
  "updated": "2026-02-01T11:00:00Z",
  "sources": [
    {
      "title": "Anatomy Reference Pack",
      "publisher": "Example Publisher",
      "url": "https://example.com/anatomy-pack",
      "primary": true
    }
  ],
  "authors": ["Third Author"],
  "released": "2024-11-08",
  "description": "Anatomy reference images.",
  "advertised_tags": ["reference", "anatomy"],
  "extra_tags": [],
  "original_size": 2147483648,
  "current_size": 2147483648,
  "reference_images": {
    "format_version": 0,
    "collections": [],
    "learning_paths": [],
    "images_count": null,
    "complete": true,
    "online": false,
    "viewed": false,
    "todo": false,
    "keep": false,
    "favorite": false,
    "rating": 0
  }
}
```

### Collection — common core only, year-only date (field set provisional, §17.2.1)

```json
{
  "format_version": 1,
  "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
  "type": "Collection",
  "created": "2026-01-10T08:00:00Z",
  "updated": "2026-01-10T08:00:00Z",
  "sources": [
    {
      "title": "Sculpting Series",
      "publisher": "Example Publisher",
      "url": "https://example.com/series",
      "primary": true
    }
  ],
  "authors": ["First Author"],
  "released": "2025",
  "description": "The full sculpting series.",
  "advertised_tags": ["sculpting", "series"],
  "extra_tags": []
}
```
