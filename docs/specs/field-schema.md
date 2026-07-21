# §17. Field Schema (v1, `.tc`-compatible)

[[[field-schema]]]

## Overview

[[[field-schema#overview]]]

- [x] [#6: decision: tutorial and reference-image field lists](https://github.com/borco/rehuco/issues/6)

The concrete starting field set for rehuco, derived from the fields a real tutcatalog4 (tc4)
`.tc` file carries. [[data-model#rehu-format]] settles the *scope* of the `.rehu` schema and defers the detail here.

## §17.1 Scope and intent

[[[field-schema#scope-and-intent]]]

The first release must **double-click an existing `.tc` and view it**. That goal — not a
speculative ideal schema — fixes the starting field set: rehuco has to accommodate whatever
tc4 actually stored.

- **Ground truth is tc4**, the only predecessor actually used to view and edit `.tc` files.
  Its data model (`Tutorial`) and viewer (`Viewer.qml`) are the reference, not the later
  tc5/resource-hub rewrites (design drafts, never shipped for this purpose).
- **`.tc` is YAML; `.rehu` is JSON** ([[data-model#rehu-format]]). v1 reads `.tc` through an adapter into rehuco's
  model; it does not write `.tc`. No line of the old reader survives verbatim — only its
  field list drives the mapping.
- **View-only defers editing-era calls** (e.g. whether dropped flags resurface as tags), but
  the schema is modeled at its **target shape** where that costs nothing — notably `sources`
  (title + publisher + URL per platform, [[field-schema#sources]]), which a legacy `.tc` fills as one primary
  entry. The `collections` / `learning_paths` membership fields are modeled too ([[field-schema#sources]]); only
  the Collection *type*'s field set stays deferred ([[field-schema#resource-types]]).

## §17.2 Field mapping: tc4 `.tc` → rehuco

[[[field-schema#field-mapping]]]

Every key a tc4 `.tc` carries, with its rehuco disposition. "Group" is the common/plugin split
([[data-model#rehu-format]], [[plugins#overview]]) and says **where the field lives on disk**: `common` at the top
level, everything
else under the type's plugin block ([[field-schema#resource-types]]). The boundary can be refined post-v1 since the
generic editor ([[plugins#fallback-editor]]) does not depend on it.

| `.tc` key | tc4 label | rehuco field | type | group | shape | disposition |
| --- | --- | --- | --- | --- | --- | --- |
| `type` | — | `core.type` | enum | common | tutorial / reference_images / collection | keep — selects resource type / plugin; tc4's capitalized spellings are aliases and normalize on write ([[plugins#core-vs-plugin]]) |
| `title` | Title | `sources[].title` | text | common | record + primary¹ | keep — see [[field-schema#sources]] |
| `publisher` | Publisher | `sources[].publisher` | text | common | record¹ | keep — see [[field-schema#sources]] |
| `url` | Homepage | `sources[].url` | URL | common | record¹ | keep — see [[field-schema#sources]] |
| `author` | Authors | `authors` | text list | common | multi | keep, rename to `authors`; stays separate²; entries string or `{name, url}` ([[field-schema#authors]]) |
| `released` | Released | `released` | date | common | partial-precision | keep — Y / Y-M / Y-M-D; content publication date |
| — | *(none in tc4)* | `created` | datetime | common | scalar | **new** — record created; seed from file timestamp on import |
| — | *(none in tc4)* | `updated` | datetime | common | scalar | **new** — record last edited; seed from file mtime on import |
| `description` | *(bottom pane)* | `description` | Markdown | common | scalar | keep — embeds sibling `infoXX` images |
| `tags` | Tags | `advertised_tags` | text list | common | multi | keep, rename — web-scraped |
| `extraTags` | Exta Tags *(sic)* | `extra_tags` | text list | common | multi | keep, rename to snake_case — personal edits |
| `original_size` | Original size | `original_size` | size (bytes) | common | scalar | keep — see [[field-schema#duration-size]]; empty for Collection |
| `current_size` | Current size | `current_size` | size (bytes) | common | scalar | keep — see [[field-schema#duration-size]]; empty for Collection |
| `complete` | Complete | `complete` | bool | Tutorial, RefImages | scalar | keep — "all files present"; default `true` |
| `online` | Online | `online` | bool | Tutorial, RefImages | scalar | keep — "source still available online" ([[field-schema#online-flag]]) |
| `rating` | Rating | `rating` | rating (int) | Tutorial, RefImages | scalar | keep — **per-user**; may be negative |
| `viewed` | Viewed | `viewed` | bool | Tutorial, RefImages | scalar | keep — **per-user** |
| `todo` | To Do | `todo` | bool | Tutorial, RefImages | scalar | keep — **per-user** |
| `keep` | Keep | `keep` | bool | Tutorial, RefImages | scalar | keep — **per-user** |
| — | *(new)* | `favorite` | bool | Tutorial, RefImages | scalar | **new** — **per-user**; separate UI ([[field-schema#boolean-flags]]) |
| `collection` | Collection | `collections[].title` | text | Tutorial, RefImages | record³ | keep — see [[field-schema#sources]] |
| `collection_index` | Index | `collections[].index` | int | Tutorial, RefImages | record³ | keep — see [[field-schema#sources]] |
| `learning_paths` | Learning Paths | `learning_paths[].title` (+ `.index`) | record | Tutorial, RefImages | multi, user-defined⁴ | keep — see [[field-schema#sources]] |
| `duration` | Duration | `original_duration` (+ `current_duration`, `advertised_duration`) | duration (seconds) | Tutorial | scalar | keep, split — see [[field-schema#duration-size]] |
| `level` | Level | `level` | multi-choice | Tutorial | multi | keep — beginner / intermediate / advanced / any |
| — | *(none in tc4)* | `images_count` | int | ReferenceImages | scalar | **new** — empty on import (not from `duration`), filled by scanning ([[field-schema#deferred-items]]) |

¹ `sources` is a list; each item is `{ title, publisher, url, primary? }`. The item with
`primary: true` (or the first item if none is flagged) is canonical — its **title** is the
display title and the basis for folder/file-name suggestions ([[field-schema#sources]]).
² **`authors` stays one shared list**, not per-source — a differing author set signals a
*different* tutorial, not another source of the same one ([[field-schema#sources]]).
³ one **collection membership** = `{ title, index, url? }`; a resource may belong to several
series ([[field-schema#sources]]).
⁴ **learning paths** are `{ title, index, visibility }`; `visibility` is the UI `public` /
`private` toggle; the owner is implicit by per-user block ([[field-schema#sources]]).

Values tc4 derives rather than stores (not `.tc` keys): the folder/parent path (from the file
location), canonical folder-name suggestions, and the transient "Computed" duration/size from a
disk scan (which in rehuco feed `current_duration` / `current_size` — see [[field-schema#duration-size]]).

### §17.2.1 Resource types

[[[field-schema#resource-types]]]

`type` selects one of three. Fields fall into tiers so "common" means *common to all types*
only:

- **Common core (all types)** — `sources` (title/publisher/url), `authors`, `released`,
  `description`, `advertised_tags`, `extra_tags`, `created`, `updated`, and the measured
  `original_size` / `current_size` pair ([[field-schema#duration-size]]) — the sizes are core-scanner output, wanted by
  every file-backed type; a Collection leaves them empty (it may later fill them from member
  stats — see the Collection bullet below).
- **Resource fields (Tutorial + ReferenceImages)** — `rating`, the boolean flags
  (`complete`, `online`, `viewed`, `todo`, `keep`, `favorite`; [[field-schema#boolean-flags]]), and the `collections` /
  `learning_paths` memberships ([[field-schema#sources]]). A **Collection** declares none of these.
- **Tutorial only** — `original_duration` / `current_duration` / `advertised_duration` and
  `level`.
- **ReferenceImages only** — `images_count`; declares **no** duration ([[field-schema#duration-size]]), so the value
  that leaked as `720` in tc4 has nowhere to land.
- **Collection** — a series/grouping node; its **`title` is the series name** that members
  reference via `collections[].title`. **Which fields it shows/edits is deferred** until a real
  collection is in hand ([[field-schema#deferred-items]]), including whether it carries a recomputed member-stats cache
  (in tc4 the extra fields it held were only such a cache, sparing a descent into member
  subfolders). This is separate from the `collections` membership fields, which are settled
  ([[field-schema#sources]]).

**On disk:** the common core is nested in the reserved **`core` block**; every non-common field is nested under a
**plugin block keyed by `type`** (`tutorial`, `reference_images`), each carrying its own `format_version`
([[data-model#rehu-format]], [[data-model#schema-version]], [[plugins#plugin-blocks]]), so the file already has the
plugin shape and won't need restructuring when plugins land. A block `format_version` of **0 means "no plugin yet"** —
the fields live there but no plugin owns them; **`1`** is the first defined block layout — per-user state nested under
the block's `users` map ([[field-schema#per-user-shared]]). Fields shared by Tutorial and
ReferenceImages (`rating`, the boolean flags, `collections`, `learning_paths`)
live inside whichever plugin block the file has — the per-user subset under `users`. Collection has no block yet. See
the [[field-schema#example-files]]
fixtures.

### §17.2.2 Per-user vs shared

[[[field-schema#per-user-shared]]]

- [x] [#98: feat: per-user state under the plugin block's users map (block layout v1 + identity setting)](https://github.com/borco/rehuco/issues/98)
- [x] [#99: feat: identity setting + per-user model plumbing over the users map](https://github.com/borco/rehuco/issues/99)
- [x] [#109: feat: current + unknown identities — .tc imports file per-user state under "unknown", UI edits under the current user](https://github.com/borco/rehuco/issues/109)

`rating`, the per-user boolean flags (`viewed`, `todo`, `keep`, `favorite`), and **private**
`learning_paths` are **per-user** state, not properties of the resource. v1 is single-user/local
so this is invisible, but the schema must keep them separable from shared fields so the
multi-user model ([[sync#overview]], [[data-model#rehu-format]]'s per-user `progress`) does not have to relocate them
later. The
shared flags (`complete`, `online`) and a learning path toggled **public** (or curated by the
admin) are propagated swarm state instead ([[field-schema#sources]], [[field-schema#boolean-flags]]).

**Stored per-user from day 1 — nested under the block's `users` map, keyed by username** (decided 2026-07, superseding
the earlier live-inline-for-now deferral):

```json
"users": { "admin": { "favorite": true, "rating": 4, "viewed": false } }
```

- **Why now:** migrations can reshape layout but cannot mint facts — a later inline→per-user move would have to
  *guess* whose flags these were, per file, on whichever machine touched it first. Recording the owner at write time
  is the only unambiguous version, and the single-user era is when the assignment is a fact rather than a guess. The
  **block `format_version` 1** defines this layout, and the v0→v1 block migration (moving inline per-user keys under
  the currently configured username) is written while that still holds.
- **The identity is an app setting — two usernames, by provenance** (#109): the **current** user, who *this
  install's* own UI edits are filed under (seeded from the OS login name, `admin` as the fallback), and the
  **unknown** user (default `unknown`), who **imported** per-user state is filed under — a favorite/rating
  carried in from a `.tc` was *not* set by this identity here, so its real owner is unknown. The editor's
  per-user writes go to the current user; the `.tc` importer files under the unknown one. Both are editable on
  the settings identity page, and setting them to the same value (collapsing back to one identity) is
  supported — no uniqueness constraint. A just-imported resource opened for editing carries its foreign
  per-user data under `unknown` **verbatim**, preserved untouched on round-trip; reassigning or dropping it is
  deferred (#106 / #107).
- **Keyed by username, not a minted user-UUID — considered and rejected:** pre-swarm, files move between machines by
  manual copy, and per-machine UUIDs could never merge state the same human owns, while equal usernames merge by
  construction. The cost — renaming a user rewrites files — is a rare, catalog-cache-era task-queue job (mass
  rename), cheap once the cache knows every file naming the user.
- **The future user model adopts it unchanged:** swarm users ([[discovery-trust-access#user-auth]]) take over the
  username; per-user `progress` and Daz3D's per-user/per-box `installed` land in the same map.

### §17.2.3 Sources (multi title / publisher / URL)

[[[field-schema#sources]]]

One resource can be published in several places — the same tutorial sold on more than one
platform under slightly different names and links ([[data-model#rehu-format]]). This is modeled as `sources`:

```yaml
sources:
  - { title, publisher, url, primary: true }
  - { title, publisher, url }
```

- `sources` is a **list**; each item binds a `{ title, publisher, url }` for one platform,
  replacing tc4's scalar `title` / `publisher` / `url` (the "Homepage").
- The item flagged **`primary: true`** is canonical (an inline marker, not a positional index).
  Its **title** is the display title and the basis for the folder/file-name suggestion widget
  ([[data-model#rehu-format]]).
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
  curate public ones, [[discovery-trust-access]]). The **owner stays implicit** — a personal path lives in that user's
  per-user block ([[field-schema#per-user-shared]]), so we store the **`visibility` flag, not a `user` field**. Public
  paths are propagated swarm state; private ones stay per-user, mirroring `rating` / `viewed` /
  `progress` ([[sync#overview]]). v1 is single-user, so the public/private split only bites once there's a
  swarm.
- **Legacy import** — scalar `collection` + `collection_index` become one entry; the flat
  `learning_paths` names become entries with `index` by stored order.

Only the **Collection *type*** stays deferred — which fields a `type: Collection` record
shows/edits, and whether it carries a recomputed member-stats cache ([[field-schema#resource-types]],
[[field-schema#deferred-items]]). The
membership *fields* above are settled.

Collections and learning paths (with authors) later gain optional **entity documents** — discovered vs. genuine,
entity-as-authority, materialize-on-description — as grouping-entity plugins ([[plugins#grouping-entities]]); the
membership fields above are the reference mechanism that design builds on and are unchanged on disk by it.

### §17.2.4 The `online` flag and local backup

[[[field-schema#online-flag]]]

`online` means **the original source is still available online** — not "this is an online-only
resource" (the ambiguity [[data-model#rehu-format]] warns against). The driving case: many Udemy-style courses are
kept as just a `.rehu` with screenshots plus a pointer to the source (the primary listing's
`url`); the point of the flag is that the course can still be reached at that source.

It is **independent of whether the content is stored locally.** A resource can be
online-and-backed-up, online-but-screenshots-only (no local content), or offline-but-archived.
Local presence is read from `current_size` / `complete`, not from `online`. The tc4 name
**`online` is kept** — with the meaning documented here there is no competing "online-only"
sense to disambiguate against, so the finer `source_online` / `available_online` rename is not
worth it.

### §17.2.5 Record timestamps

[[[field-schema#record-timestamps]]]

`created` and `updated` are **new** full datetime values (not the partial-precision `released`, which
is the *content's* publication date): when the `.rehu` record was first written and last
edited. tc4 stored neither; on import they seed from the file's timestamps. They are shared
record state (an edit that syncs updates `updated`), and relate to the `resource_version` /
timestamp markers used for staleness detection and sync ([[data-model#scan-and-staleness]]).

Once the `versions` list lands in the schema ([[sync#overview]] — v1 carries no versions yet), both become
**derivable**: `created` = the creation entry's date (index 0, which compaction never touches,
[[sync#overview]]) and `updated` = the latest entry's date. A later format version may then drop the stored
fields in favor of the derived values — [[data-model#schema-version]] makes that migration safe.

### §17.2.6 Boolean flags

[[[field-schema#boolean-flags]]]

For v1 the tc4 boolean flags stay **individual booleans**, as in tc4 — `complete`, `online`
([[field-schema#online-flag]]), `viewed`, `todo`, `keep` — plus a new `favorite`. Import is 1:1 (each tc4 bool maps
to the same-named bool); `favorite`, absent from tc4, defaults to `false`.

- **`favorite` is kept separate**, not lumped with the rest: it carries different semantics (it
  can drive behavior beyond a display flag) and its control may sit in a different place in the
  UI.
- **Scope.** `complete` and `online` are shared/objective; `viewed`, `todo`, `keep`, `favorite`
  are **per-user** ([[field-schema#per-user-shared]]) — inline for now ([[field-schema#deferred-items]]).
- **Deferred: a `default_tags` toggle set.** Folding the fixed-vocabulary bools
  (`complete`/`online`/`viewed`/`todo`/`keep`) into one list rendered as UI toggles, with a
  vocabulary from `.rehuco` or defaults, was considered and **deferred** ([[field-schema#deferred-items]]): its payoff
  needs the plugin/config system, and [[data-model#schema-version]]'s per-block versioning makes the bool-to-list
  migration safe to do in a later revision. `favorite` would stay separate regardless. `rating`
  never folds in (it is an integer, not a toggle).

### §17.2.7 Author entries: plain name or `{name, url}` record

[[[field-schema#authors]]]

- [x] [#92: feat: tolerant authors entries — string or {name, url} record](https://github.com/borco/rehuco/issues/92)
- [x] [#95: feat: authors viewer links (url, tooltip, status tip) + comma-editor lossless guard](https://github.com/borco/rehuco/issues/95)
- [ ] [#97: feat: record-list editor machinery + simple/advanced authors editor](https://github.com/borco/rehuco/issues/97)

`authors` entries are tolerantly **string-or-record**: a plain string is the common case, and an entry that carries an
author-page URL is a `{ "name": …, "url": … }` record instead. Decided with
[[daz3d-personal-database#authors-urls]] — the URL is useful well before any Daz3D work lands.

- **Canonical minimal form.** The record form is written only when there is a URL to carry; a record reduced to a bare
  name is written back as a plain string, so "are all entries simple?" stays a trivial test.
- **Editing follows a lossless-round-trip rule.** The comma-separated single-line editor is available **iff** every
  entry survives a round-trip through it (all plain strings, none containing a comma); otherwise only the record-list
  editor is, and the mode never switches on its own. A name containing a comma (`Foo Bar, Jr.`) is expressible only as
  a record entry — an accepted limitation of the comma delimiter, not of the format. The record-list editor is
  **deferred** (#97; today's only `.rehu` source is `.tc` import, which carries no author URLs), so until it lands a
  list failing the predicate is **view-only**: the comma editor disables itself (#95) rather than corrupt what it
  cannot represent.
- **Validation splits by side.** The editor enforces what it writes: a non-empty name, and a URL that parses strictly
  as http/https. The viewer is the safety boundary for what it reads ([[data-model#write-integrity]]): names are
  HTML-escaped before rich-text display (HTML is never *interpreted*, so no character is banned from a name), and the
  trailing `(url)` link renders only for a valid http/https value — anything else displays as if no URL were present.
  The URL shows as a tooltip and a status-bar message on hover, and opens in the external browser on click.
- **No aliases in documents.** An alias set is catalog-level identity, deferred to a future metadata-only
  **author record** type on the Collection precedent ([[field-schema#resource-types]],
  [[daz3d-personal-database#authors-urls]]); per-document URLs fold into it then. Author names additionally render as
  `filter://` links once browsers exist ([[plugins#filter-urls]]).

## §17.3 Duration and size model

[[[field-schema#duration-size]]]

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
`progress` ([[data-model#rehu-format]]). The delete-to-track-progress method does not generalize to the swarm, where
remaining-on-disk (per-node) and watch-progress (per-user) become two different things; the
schema keeps room for a separate `progress` so recording "watched" never again requires
deleting files.

`duration` does not apply to **ReferenceImages** — for that type it is an unknown field, not a
blank one, so it is simply not declared (which is what should have hidden the leaked value in
tc4's shared viewer). The leaked `720` is **not** reinterpreted as `images_count`: on import of
a reference-images `.tc` the old `duration` is dropped and `images_count` is left **empty**,
to be filled later by scanning ([[field-schema#deferred-items]]) rather than by guessing it was ever an image count.

### §17.3.1 Canonical unit and the millisecond-leak history

[[[field-schema#ms-leak-history]]]

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

[[[field-schema#duration-format]]]

Carried over verbatim from tc4 (it already matches the desired behavior), with one revision
(#101): `d` itself is `int | None` now, `None` meaning unmeasured/absent rather than a fabricated
`0` ([[field-schema#deferred-items]]). For a value `d` in seconds:

```text
if d is None:    render ""           # unmeasured -- not "0s"
if d == 0:       render "0s"         # a genuine zero renders honestly
h = d // 3600 ;  m = (d % 3600) // 60 ;  s = d % 60
parts = []
if h:            parts += "{h}h"
if m:            parts += "{m}m"
if s and h == 0: parts += "{s}s"     # seconds are noise once hours are present
render " ".join(parts)
```

- `2h 15m`, `2h` (minutes zero), `45m`, `45m 30s`, `30s`, `0s`.
- Hours are **never** rolled into days — large values read as `123h 45m`, not a time of day.

Size renders base-1000 (macOS-Finder style) with two decimals, e.g. `1.50 GB`; `None`
(unmeasured/absent) renders empty, a genuine `0` renders honestly (#101).

## §17.4 Field types

[[[field-schema#field-types]]]

The distinct value types the viewer must handle:

| type | notes |
| --- | --- |
| text | single line |
| text list | comma-joined for display, deduplicated; `authors` (entries may be `{name, url}` records, [[field-schema#authors]]), `advertised_tags`, `extra_tags` |
| url | rendered as an external hyperlink |
| date | **partial precision** — year, year+month, or full date; sorts/compares across mixed precision |
| duration | integer seconds; rendered per [[field-schema#duration-format]] |
| size | integer bytes; rendered base-1000 |
| rating | integer, may be negative; star-style widget |
| bool | yes/no; `complete` shows a warning color when false |
| multi-choice | fixed value set; `level` ∈ {beginner, intermediate, advanced, any} |
| Markdown | rich text; resolves embedded image paths relative to the file's folder |
| int | plain integer; `collection_index`, `images_count` |
| record list | list of small records; `sources`, `collections`, `learning_paths` ([[field-schema#sources]]) |

## §17.5 tc4 viewer layout (reference for the v1 view)

[[[field-schema#tc4-viewer-layout]]]

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

[[[field-schema#deferred-items]]]

- [x] [#100: feat: optional scalars read as None — absent is not 0 (core)](https://github.com/borco/rehuco/issues/100)
- [x] [#101: feat: None-aware widgets and display for optional scalars (agent)](https://github.com/borco/rehuco/issues/101)

- **Common/plugin boundary** — the [[field-schema#field-mapping]] tiers (common core / resource fields / per-type) are a
  first cut; finalize when the field toolkit (A2) and plugin blocks ([[plugins#overview]]) land. The generic
  editor does not depend on it.
- **Collection *type* — deferred** ([[field-schema#resource-types]]) — which fields a `type: Collection` record
  shows/edits, and whether it re-gains a **recomputed** member-stats cache. Decide when a real
  collection is in hand. *(The `collections` membership fields are settled, [[field-schema#sources]].)* Partially
  designed since: placement, discovered-vs-genuine, and entity authority are recorded in [[plugins#grouping-entities]];
  only the type's own field set still waits for a real collection.
- **Author entity plugin — deferred to the catalog-cache era** — aliases and per-store URLs as a metadata-only
  grouping-entity type ([[plugins#grouping-entities]], [[daz3d-personal-database#authors-urls]]), arriving with
  Milestone B's `.rehudb` (its browser/aggregation UI is what needs the cache); documents reference authors by
  credited name until then, and per-document `{name, url}` entries ([[field-schema#authors]]) fold into the entity
  when it lands.
- **Optional scalars read as `None` — done (#100 core, #101 display)** — absent is not `0`: the measured/claimed
  numerics (`original_size` / `current_size`, the three durations, `images_count`), `rating` (it may be negative, so
  `0` is a real rating and unrated must be `None`), and `released` read as `None` when absent; strings, lists, and the
  boolean flags keep their coercion defaults. Absent-on-disk ↔ `None`-in-code: JSON `null` is accepted on read but
  never written — setting `None` omits the key (the fixtures' `images_count: null` normalizes away on save). Display
  follows: `None` renders empty, so a genuine `0` renders honestly (revises [[field-schema#duration-format]]'s old
  "`0` renders empty" rule).
- **Membership by identity** — `collections[].title` links to a series by name today; move to
  resource identity ([[data-model#stable-identity]]) once UUIDs are minted.
- **Per-user storage — resolved** ([[field-schema#per-user-shared]]): per-user keys nest under the plugin block's
  `users` map from block layout v1. Still open here: the catalog-cache-era **mass-rename** job (old username → new,
  across every file naming the user) and where a **public** learning path lives (below).
- **Learning-path visibility storage** — the `public` / `private` toggle ([[field-schema#sources]]): confirm
  whether a public user path stays in the owner's per-user block (owner implicit) or moves to
  the shared record on toggle. Swarm-era, not v1. Refined by the grouping-entity design
  ([[plugins#grouping-entities]]): a private path likely stays pure per-user state, with the entity document minted
  **at publication** (privacy by non-existence), and ordering moves to the entity once one exists.
- **`default_tags` consolidation — deferred** ([[field-schema#boolean-flags]]) — a later revision may fold the
  fixed-vocabulary bools (`complete`/`online`/`viewed`/`todo`/`keep`) into one toggle-set list
  with a vocabulary from `.rehuco` (scope, labels/icons), migrated via a plugin-block
  `format_version` bump ([[data-model#schema-version]]). `favorite` stays separate. v1 keeps individual bools.
- **`images_count` on import** — left **empty** for a reference-images `.tc` (the old `duration`
  is not assumed to be a count); fill later by scanning the sibling `infoXX.*` set or the
  content zip.
- **`created` / `updated` seeding** — confirm which file timestamp seeds `created` on import
  (ctime is unreliable cross-platform; mtime is the safer floor).
- **Description image resolution** — confirm sibling-relative path handling matches [[data-model#image-meanings]]'s
  screenshot model.
- **UUID ([[data-model#stable-identity]]) and per-block format version ([[data-model#schema-version]],
  [[plugins#plugin-blocks]])** — minted/added when writing
  `.rehu`; not present in legacy `.tc`, so they are an import concern, not a view concern.
- **Partial-date comparison semantics** — `released` stores ISO-prefix strings (`2025`,
  `2025-03`, `2025-03-08`); lexicographic sorting already orders them sensibly, but what a
  comparison or *filter* means for a partial value (treat it as the interval it covers?) is
  not decided — pin down before filtering lands ([[field-schema#field-types]]).

## §17.7 Example `.rehu` files (validation fixtures)

[[[field-schema#example-files]]]

Concrete `.rehu` documents (JSON, [[data-model#rehu-format]]) that exercise the field set above — usable as
parser/schema validation fixtures.

- A `.rehu` is `format_version` plus a **map of keyed blocks** ([[data-model#rehu-format]]): the **common core** sits in
  the reserved `core` block, and everything a type owns is nested under a **plugin block keyed by `type`** (`tutorial` /
  `reference_images`), each with its own `format_version`
([[data-model#schema-version]], [[plugins#plugin-blocks]]) — **`0` = no plugin yet**, **`1`** = the per-user
`users`-map layout ([[field-schema#per-user-shared]]) — so the
  layout already matches the future plugin structure. A **Collection** has no block yet
  (deferred, [[field-schema#resource-types]]) and carries only common core.
- `core["type"]` **is** the active block's key ([[plugins#plugin-blocks]]), spelled with the plugin's declared main key;
  tc4's `Tutorial` / `ReferenceImages` are aliases that normalize on write ([[plugins#core-vs-plugin]]).
- `sources` is a list; exactly one item carries `primary: true`.
- **Per-user** fields (`rating`, the per-user boolean flags, private `learning_paths`) nest under the plugin block's
  `users` map, keyed by the configured username ([[field-schema#per-user-shared]]); the shared fields stay inline
  beside it.
- Values are illustrative; each example stresses the edge case named in its heading.

### Tutorial — multi-source, multi-collection, split duration, year-month date

```json
{
  "format_version": 2,
  "core": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "tutorial",
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
    "current_size": 1073741824
  },
  "tutorial": {
    "format_version": 1,
    "collections": [
      { "title": "Sculpting Series", "index": 1, "url": "https://example.com/series" },
      { "title": "Bundle 2025", "index": 10 }
    ],
    "original_duration": 71220,
    "current_duration": 18000,
    "advertised_duration": 72000,
    "level": ["intermediate"],
    "complete": true,
    "online": true,
    "users": {
      "admin": {
        "favorite": true,
        "keep": false,
        "learning_paths": [
          { "title": "My Sculpting Path", "index": 2, "visibility": "private" }
        ],
        "rating": 4,
        "todo": false,
        "viewed": false
      }
    }
  }
}
```

### ReferenceImages — absent `images_count`, no duration, full date, unrated

```json
{
  "format_version": 2,
  "core": {
    "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "type": "reference_images",
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
    "current_size": 2147483648
  },
  "reference_images": {
    "format_version": 1,
    "collections": [],
    "complete": true,
    "online": false,
    "users": {
      "admin": {
        "favorite": false,
        "keep": false,
        "todo": false,
        "viewed": false
      }
    }
  }
}
```

### Collection — common core only, year-only date (provisional)

Field set provisional ([[field-schema#resource-types]]).

```json
{
  "format_version": 2,
  "core": {
    "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    "type": "collection",
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
}
```
