# §17. Field Schema (v1, `.tc`-compatible)

[[[field-schema]]]

## Overview

[[[field-schema#overview]]]

- [#6: decision: tutorial and reference-image field lists](https://github.com/borco/rehuco/issues/6)

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

- [#196: feat: surface images_count as a ReferenceImages-only field](https://github.com/borco/rehuco/issues/196)
- [#198: feat: compute the content-image count — advertised_count / current_count with a measure/apply
  row](https://github.com/borco/rehuco/issues/198)

Every key a tc4 `.tc` carries, with its rehuco disposition. "Group" is the common/plugin split
([[data-model#rehu-format]], [[plugins#overview]]) and says **where the field lives on disk**: `common` in the reserved
`core` block, everything else under the type's plugin block ([[field-schema#resource-types]]). The boundary can be
refined post-v1 since the
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
| — | *(new)* | `hidden_images` | text list | common | multi | **new** — screenshot basenames curated *out* of the lightbox ([[data-model#image-meanings]], #27); absent/empty = all shown |
| `tags` | Tags | `advertised_tags` | text list | common | multi | keep, rename — web-scraped |
| `extraTags` | Exta Tags *(sic)* | `extra_tags` | text list | common | multi | keep, rename to snake_case — personal edits |
| `original_size` | Original size | `original_size` | size (bytes) | common | scalar | keep — see [[field-schema#duration-size]]; empty for Collection |
| `current_size` | Current size | `current_size` | size (bytes) | common | scalar | keep — see [[field-schema#duration-size]]; empty for Collection |
| `complete` | Complete | `complete` | bool | Tutorial, RefImages | scalar | keep — "all files present"; default `true` |
| `online` | Online | `online` | bool | Tutorial, RefImages | scalar | keep — "source still available online" ([[field-schema#online-flag]]) |
| `rating` | Rating | `rating` | rating (int) | Tutorial, RefImages | scalar | keep — **per-user**; may be negative |
| `viewed` | Viewed | `viewed` | bool | Tutorial | scalar | keep — **per-user**; Tutorial-only since #195 ([[field-schema#boolean-flags]]) |
| `todo` | To Do | `todo` | bool | Tutorial | scalar | keep — **per-user**; Tutorial-only since #195 ([[field-schema#boolean-flags]]) |
| `keep` | Keep | `keep` | bool | Tutorial, RefImages | scalar | keep — **per-user** |
| — | *(new)* | `favorite` | bool | Tutorial, RefImages | scalar | **new** — **per-user**; separate UI ([[field-schema#boolean-flags]]) |
| `collection` | Collection | `collections[].title` | text | Tutorial, RefImages | record³ | keep — see [[field-schema#sources]] |
| `collection_index` | Index | `collections[].index` | int | Tutorial, RefImages | record³ | keep — see [[field-schema#sources]] |
| `learning_paths` | Learning Paths | `learning_paths[].title` (+ `.index`) | record | Tutorial, RefImages | multi, user-defined⁴ | keep — see [[field-schema#sources]] |
| `duration` | Duration | `original_duration` (+ `current_duration`, `advertised_duration`) | duration (seconds) | Tutorial | scalar | keep, split — see [[field-schema#duration-size]] |
| `level` | Level | `level` | multi-choice | Tutorial | multi | keep — beginner / intermediate / advanced / any |
| — | *(none in tc4)* | `current_count` | int | ReferenceImages | scalar | **new** — empty on import (not from `duration`), filled by scanning ([[field-schema#deferred-items]]); spelled `images_count` until [#198](https://github.com/borco/rehuco/issues/198), renamed on load by the block chain's v4 step |
| — | *(none in tc4)* | `advertised_count` | count claim (text) | ReferenceImages | scalar | **new** — what the pack claims of itself; text, so an open-ended `500+` stays weaker than `500` ([[field-schema#field-types]]) |

¹ `sources` is a list; each item is `{ title, publisher, url, primary? }`. The item with
`primary: true` (or the first item if none is flagged) is canonical — its **title** is the
display title and the basis for folder/file-name suggestions ([[field-schema#sources]]).
² **`authors` stays one shared list**, not per-source — a differing author set signals a
*different* tutorial, not another source of the same one ([[field-schema#sources]]).
³ one **collection membership** = `{ title, index, url? }`; a resource may belong to several
series, and `url` is a cached copy of the series' own page rather than authored here
([[field-schema#sources]]).
⁴ **learning paths** are `{ title, index, ref }` when owned and `{ ref }` when subscribed, filed
under the owning identity in the block's `users` map — ownership is structural, and there is no
`visibility` flag ([[field-schema#learning-path-ownership]]).

Values tc4 derives rather than stores (not `.tc` keys): the folder/parent path (from the file
location), canonical folder-name suggestions, and the transient "Computed" duration/size from a
disk scan (which in rehuco feed `current_duration` / `current_size` — see [[field-schema#duration-size]]).

### §17.2.1 Resource types

[[[field-schema#resource-types]]]

`type` selects one of three. Fields fall into tiers so "common" means *common to all types*
only:

> [!NOTE]
> **Where a type's field list is authored: in the plugin declaration** (settled in
> [#195](https://github.com/borco/rehuco/issues/195)). A plugin declares the field *names* it
> contributes alongside its key list and badge colors ([[plugins#core-vs-plugin]]: schema extension is
> plugin-owned), and the common core declares its own the same way. Names only, no widget types — a
> node reads the same declaration to know a block's shape, and mapping a name to a toolkit widget is
> the agent's job ([[plugins#field-toolkit]]). The alternative — a per-type map in the agent's
> composition layer — was rejected as the layering inversion #151 had to undo once.
>
> Two consequences worth stating. **A type declares nothing when its plugin isn't installed here**, so
> it composes the common core alone and every key in its block reaches the generic fallback
> ([[plugins#fallback-editor]]) — narrowing what renders must never make a value invisible, so
> *recognition* narrows with it. And **the tiers below are an observation, not a third thing the
> registry knows**: Tutorial and ReferenceImages share the resource fields by both naming them, so one
> dropping a field is not a change to the other's schema.
>
> Still open: where each type's **ordered** list is authored
> ([[appendices.open-questions#still-open]]). Display order remains one hardcoded list spanning every
> type, filtered per type — the declarations are sets.

- **Common core (all types)** — `sources` (title/publisher/url), `authors`, `released`,
  `description`, `hidden_images` ([[data-model#image-meanings]]), `advertised_tags`, `extra_tags`, `created`,
  `updated`, and the measured
  `original_size` / `current_size` pair ([[field-schema#duration-size]]) — the sizes are core-scanner output, wanted by
  every file-backed type; a Collection leaves them empty (it may later fill them from member
  stats — see the Collection bullet below).
- **Resource fields (Tutorial + ReferenceImages)** — `rating`, the boolean flags
  `complete`, `online`, `keep` and `favorite` ([[field-schema#boolean-flags]]), and the `collections` /
  `learning_paths` memberships ([[field-schema#sources]]). A **Collection** declares none of these.
  `complete` belongs here rather than with the durations because it means *the item has all its parts* —
  every video of a tutorial, every image of a reference pack.
- **Tutorial only** — `original_duration` / `current_duration` / `advertised_duration`,
  `level`, and the progress flags `viewed` / `todo`. Progress through timed material is not something a
  reference-image pack has: you consult one, you don't get through it. They sat on both types until
  [#195](https://github.com/borco/rehuco/issues/195); a `reference_images` block that still carries them
  is stripped by that chain's **v3** step ([[plugins#plugin-blocks]]), which is the first place the two
  block chains diverge.
- **ReferenceImages only** — the count pair `advertised_count` / `current_count` (what the pack claims,
  and what counting its archives finds — [[data-model#resource-scoping]]); declares **no** duration
  ([[field-schema#duration-size]]), so the value
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

- [#98: feat: per-user state under the plugin block's users map (block layout v1 + identity setting)](https://github.com/borco/rehuco/issues/98)
- [#99: feat: identity setting + per-user model plumbing over the users map](https://github.com/borco/rehuco/issues/99)
- [#109: feat: current + unknown identities — .tc imports file per-user state under "unknown", UI edits under the current user](https://github.com/borco/rehuco/issues/109)

`rating`, the per-user boolean flags (`viewed`, `todo`, `keep`, `favorite`), and **all**
`learning_paths` are **per-user** state, not properties of the resource. v1 is single-user/local
so this is invisible, but the schema must keep them separable from shared fields so the
multi-user model ([[sync#overview]], [[data-model#rehu-format]]'s per-user `progress`) does not have to relocate them
later. The shared flags (`complete`, `online`) and the `collections` memberships are properties of the
resource and stay inline in the block ([[field-schema#sources]], [[field-schema#boolean-flags]]).

**The map is keyed by scope, not strictly by person.** Two of its keys are not people: `unknown`, which
imported state is filed under because its real owner is unknown (below), and the reserved `public`,
which holds learning paths shared with everyone ([[field-schema#learning-path-ownership]]). `public`
must be **reserved** — unlike `unknown`, which is a configurable setting — since a real user by that
name would silently become the publishing scope, the same way `RESERVED_KEYS` protects `core` from a
plugin claiming it ([[data-model#rehu-format]]).

**Private is not secret.** A private path is one that is *not propagated as swarm state and not shown in
another user's viewer* — it is not hidden from anyone with the file. The `users` map is a **convention,
not a boundary**: any process that can read the document reads all of it, and two of the app's own docks
already print it verbatim ([[field-schema#source-inspection-docks]]). What each surface shows is a presentation
rule, applied consistently:

| Surface | Shows |
| --- | --- |
| Viewer | the current identity's own state only — one user's values never see another's |
| Editor | the file's editable content, other users' paths included, so subscribing is possible |
| Save Preview / On Disk | everything, unfiltered — that is what they are for |

**Stored per-user from day 1 — nested under the block's `users` map, keyed by username** (decided 2026-07, superseding
the earlier live-inline-for-now deferral):

```json
"users": { "admin": { "favorite": true, "rating": 4, "viewed": false } }
```

- **Why now:** migrations can reshape layout but cannot mint facts — a later inline→per-user move would have to
  *guess* whose flags these were, per file, on whichever machine touched it first. Recording the owner at write time
  is the only unambiguous version, and the single-user era is when the assignment is a fact rather than a guess. The
  **block `format_version` 1** defines this layout, and the v0→v1 block migration (moving inline per-user keys under
  the currently configured username) is written while that still holds — and **declines when the block already carries
  a `users` map** (#134), so a v1 block re-run through it is never clobbered.
- **The identity is an app setting — two usernames, by provenance** (#109): the **current** user, who *this
  install's* own UI edits are filed under (seeded from the OS login name, `admin` as the fallback), and the
  **unknown** user (default `unknown`), who **imported** per-user state is filed under — a favorite/rating
  carried in from a `.tc` was *not* set by this identity here, so its real owner is unknown. The editor's
  per-user writes go to the current user; the `.tc` importer files under the unknown one. Both are editable on
  the settings identity page, and setting them to the same value (collapsing back to one identity) is
  supported — no uniqueness constraint. A just-imported resource opened for editing carries its foreign
  per-user data under `unknown` **verbatim**, preserved untouched on round-trip; reassigning or dropping it is
  deferred to the username mass-rename job (#108; the earlier per-identity reassign/clear primitives #106 / #107 were
  closed not-planned).
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
  `type: Collection` record's `title`); `index` is the position within that series. **Publisher-defined.**
- `url` is a **cached copy** of the series' own page, not authored here: the page belongs to the
  collection, which owns it once rather than once per member ([[plugins#grouping-entities]]). It is carried
  through untouched and gets **no editor cell** — the same child-caches-what-the-entity-owns rule the
  membership entries themselves follow. It never arrives from a `.tc`, which has no such field.
- **Duplicate `(title, index)` pairs are legal**, and entries sharing an `index` order
  **alphabetically by title**. `index` is a position, not a key: nothing enforces uniqueness, because
  the only writer that could is the entity, and it does not exist yet.
- **Renumbering every member of a collection** — dragging one into a new position and rewriting the
  rest — is an entity-era, multi-file operation ([[plugins#grouping-entities]]), not something a
  single document's editor can do.
- **`learning_paths`** use the `{ title, index }` shape and render apart from the tag fields (a plain
  tag can't carry an order), but they are **owned**, which collections are not — see
  [[field-schema#learning-path-ownership]] for the storage that expresses it.
- **Legacy import** — scalar `collection` + `collection_index` become one entry; the flat
  `learning_paths` names become owned entries under the importing identity, each with **`index: 0`**.
  tc4's list order was list order, never a curated position, so numbering them 1, 2, 3 … would mint an
  authority the source never had — the same reason absent scalars are omitted rather than defaulted
  ([[field-schema#deferred-items]]). All-zero plus the alphabetical tie-break above reads as *no order
  chosen yet*, which is the truth.

Only the **Collection *type*** stays deferred — which fields a `type: Collection` record
shows/edits, and whether it carries a recomputed member-stats cache ([[field-schema#resource-types]],
[[field-schema#deferred-items]]). The
membership *fields* above are settled.

Collections and learning paths (with authors) later gain optional **entity documents** — discovered vs. genuine,
entity-as-authority, materialize-on-description — as grouping-entity plugins ([[plugins#grouping-entities]]); the
membership fields above are the reference mechanism that design builds on and are unchanged on disk by it.

### §17.2.4 Learning-path ownership: owned, subscribed, public

[[[field-schema#learning-path-ownership]]]

- [#188: feat: import learning paths as owned entries — index 0, no visibility, minted ref](https://github.com/borco/rehuco/issues/188)
- [#189: fix: surface collections and learning paths — stop calling a v1 field a future one](https://github.com/borco/rehuco/issues/189)
- [#235: feat: memberships table editor — collections and learning paths](https://github.com/borco/rehuco/issues/235)

A collection is publisher-defined and belongs to nobody, so its entries sit inline in the plugin block.
A **learning path is somebody's** — one person curates its order — so its entries live in the block's
`users` map ([[field-schema#per-user-shared]]) and ownership is expressed by **where the entry sits and
what it carries**, with no `owner` field and no `visibility` flag:

```json
"users": {
  "public": { "learning_paths": [ { "title": "Sculpting Fundamentals", "index": 3, "ref": 1 } ] },
  "admin":  { "learning_paths": [ { "ref": 1 },
                                  { "title": "My Sculpting Order", "index": 7, "ref": 2 } ] },
  "foo":    { "learning_paths": [ { "ref": 1 }, { "ref": 2 } ] }
}
```

- **A full entry (`title`, `index`, `ref`) is an owned path.** Whoever holds it owns it — ownership is
  structural, so there is nothing to record at creation and nothing a later migration would have to guess.
- **A bare `{ ref }` is a subscription** to the owned entry carrying that `ref` in the same file. A
  subscriber has no title and no index of their own: a differently-named path is nobody's idea of a
  feature, and a different order means *a different path*, which they are free to own. So an owner's fix
  reaches every subscriber with no work, and one resource can sit at different positions in several paths
  by belonging to several.
- **`ref` is a file-scoped slot** — a small integer, unique across every block in that file, minted when
  a path is created. Deliberately not a UUID and never compared across files: it exists so a subscription
  survives its owner retitling the path, which linking by name could not.
- **`public` is a reserved scope**, not a user. Publishing **copies** a full entry into it; the original
  is untouched, so there is no un-publish — only deleting the public copy, which leaves every private one
  standing. A public path is visible to everyone without subscribing; subscription is for *other users'*
  paths.
- **An unresolvable `ref` is ignored** on read and dropped on the next save — a subscription whose target
  is gone is nothing, and must not render blank or raise.
- **An owner deleting a path that others subscribe to reparents it to the `unknown` identity** rather
  than stranding them, which leaves it ownerless and so maintainable only by the admin. With no
  subscribers it simply goes. (`unknown` is a configurable setting rather than a reserved name, so an
  install that points it at a real person inherits such paths — the same quirk imports already have.)
- **The document editor has no global rename.** Editing an owned entry's title renames the path **in this
  file**; other files keep the old name until the catalog can update them ([[plugins#grouping-entities]]).
  The cell is editable and says so, rather than being disabled for a limit that is temporary and usually
  irrelevant — most paths have one owner and one file's worth of members.

**Ordering is the entity's, cached on the members.** The per-member `index` is the pre-entity form of the
ordered item list a materialized learning path will own ([[plugins#grouping-entities]]); when one exists,
the members keep their copies *"not for authority but for self-description"*, so nothing here is undone by
that arrival.

### §17.2.5 The `online` flag and local backup

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

### §17.2.6 Record timestamps

[[[field-schema#record-timestamps]]]

`created` and `updated` are **new** full datetime values (not the partial-precision `released`, which
is the *content's* publication date): when the `.rehu` record was first written and last
edited. tc4 stored neither; on import they seed from the file's timestamps. Both are stored as
second-precision UTC ISO-8601 (`2026-01-15T09:30:00Z` — the example files' format).

`created` is stamped by the **save that first writes the record's file** — a document born in the app,
or mapped from a `.tc` that has no `.rehu` yet, has never been written until then. A value already
there is never overwritten (import seeds it from the `.tc`'s mtime), and a `.rehu` that simply carries
none keeps none: stamping on a later re-save would claim the record was created at that moment.

`updated` refreshes when a **save actually changes the record**: `save()` compares the canonical
serialization against the load/last-save baseline and stamps the save's own UTC time only when they
differ. A save that rewrites an *unchanged* record — a format-upgrade restamp, a save-as copy —
leaves it alone: writing is not editing, and "record last edited" must not decay into "record last
written". They are shared record state (a synced edit carries its refreshed `updated` with it), and
relate to the `resource_version` / timestamp markers used for staleness detection and sync
([[data-model#scan-and-staleness]]).

Once the `versions` list lands in the schema ([[sync#overview]] — v1 carries no versions yet), both become
**derivable**: `created` = the creation entry's date (index 0, which compaction never touches,
[[sync#overview]]) and `updated` = the latest entry's date. A later format version may then drop the stored
fields in favor of the derived values — [[data-model#schema-version]] makes that migration safe.

### §17.2.7 Boolean flags

[[[field-schema#boolean-flags]]]

For v1 the tc4 boolean flags stay **individual booleans**, as in tc4 — `complete`, `online`
([[field-schema#online-flag]]), `viewed`, `todo`, `keep` — plus a new `favorite`. Import is 1:1 (each tc4 bool maps
to the same-named bool); `favorite`, absent from tc4, defaults to `false`.

- **`favorite` is kept separate**, not lumped with the rest: it carries different semantics (it
  can drive behavior beyond a display flag) and its control may sit in a different place in the
  UI.
- **Scope.** `complete` and `online` are shared/objective; `viewed`, `todo`, `keep`, `favorite`
  are **per-user** ([[field-schema#per-user-shared]]) — stored under the block's `users` map, keyed by username
  (block layout v1, [[field-schema#per-user-shared]]). Per-user is a *storage* question, and orthogonal to
  which types have the field: `viewed` and `todo` are per-user **and** Tutorial-only
  ([[field-schema#resource-types]]), while `keep` and `favorite` are per-user on both types.
- **Which types.** `complete`, `online`, `keep` and `favorite` are on Tutorial and ReferenceImages;
  `viewed` and `todo` are Tutorial-only. `complete` reads as *has all its parts* — every video, or every
  image — so it is not a progress flag despite sitting near two.
- **Deferred: a `default_tags` toggle set.** Folding the fixed-vocabulary bools
  (`complete`/`online`/`viewed`/`todo`/`keep`) into one list rendered as UI toggles, with a
  vocabulary from `.rehuco` or defaults, was considered and **deferred** ([[field-schema#deferred-items]]): its payoff
  needs the plugin/config system, and [[data-model#schema-version]]'s per-block versioning makes the bool-to-list
  migration safe to do in a later revision. `favorite` would stay separate regardless. `rating`
  never folds in (it is an integer, not a toggle).

### §17.2.8 Author entries: plain name or `{name, url}` record

[[[field-schema#authors]]]

- [#92: feat: tolerant authors entries — string or {name, url} record](https://github.com/borco/rehuco/issues/92)
- [#95: feat: authors viewer links (url, tooltip, status tip) + comma-editor lossless guard](https://github.com/borco/rehuco/issues/95)
- [#97: feat: record-list editor machinery + simple/advanced authors editor](https://github.com/borco/rehuco/issues/97)

`authors` entries are tolerantly **string-or-record**: a plain string is the common case, and an entry that carries an
author-page URL is a `{ "name": …, "url": … }` record instead. Decided with
[[daz3d-personal-database#authors-urls]] — the URL is useful well before any Daz3D work lands.

- **Canonical minimal form.** The record form is written only when there is a URL to carry; a record reduced to a bare
  name is written back as a plain string, so "are all entries simple?" stays a trivial test.
- **Editing follows a lossless-round-trip rule.** The comma-separated single-line editor is available **iff** every
  entry survives a round-trip through it (all plain strings, none containing a comma); otherwise only the record-list
  editor is, and the mode never switches on its own. A name containing a comma (`Foo Bar, Jr.`) is expressible only as
  a record entry — an accepted limitation of the comma delimiter, not of the format. Both modes ship (#97): the
  editor row's misc-column toggle picks between them, the choice is remembered per resource, and a value the comma
  line cannot represent is shown as rows *without* rewriting that choice — so it returns to the comma line the moment
  the value can be shown there again. While that holds the toggle is disabled and says why, which is what the
  view-only lock indicator #95 put in that column was standing in for.
- **A row writes back into the entry it was built from**, changing only the field it owns, so a key beyond `name` and
  `url` — a later schema version's addition — survives an edit to the name beside it. Reconstructing the entry from
  the two cells would drop it on an entry nobody meant to touch, which is an *invisible* loss; an extra key is an
  unknown field, not a coercion failure, so it does not lock the document either ([[data-model#schema-version]]).
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
tc4's shared viewer). The leaked `720` is **not** reinterpreted as an image count: on import of
a reference-images `.tc` the old `duration` is dropped and `current_count` is left **empty**,
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
  genuinely long collections. **That scan exists since
  [#224](https://github.com/borco/rehuco/issues/224)**, as a compute/apply row on each measured
  duration — so an imported value stays advisory only until someone presses it, and is replaced by an
  explicit click rather than silently on open.

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
| int | plain integer; `collection_index`, `current_count` (which adds a measure/apply row, [[data-model#resource-scoping]]) |
| count claim | a whole number, optionally suffixed `+` (`500`, `500+`); stored as **text**, never coerced to an integer — `advertised_count` |
| record list | list of small records; `sources`, `collections`, `learning_paths` ([[field-schema#sources]]) |

**Line endings in `description` are normalized on read, stored verbatim on write.** The `description` getter returns
LF-only text regardless of the writing platform's convention — CRLF, a bare CR, or already-LF all read as `\n` — so
editing reads identically no matter which OS wrote the file. Like every other read-time coercion
([[data-model#write-integrity]]), it does **not** mutate the backing data: an untouched description keeps its on-disk
line endings until the setter runs, and the setter stores the incoming value as-is. This is a *value* normalization on
one Markdown field, distinct from the key-order and `null`-omission normalization the serializer imposes on the whole
file ([[field-schema#canonical-order]]).

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

- [#100: feat: optional scalars read as None — absent is not 0 (core)](https://github.com/borco/rehuco/issues/100)
- [#101: feat: None-aware widgets and display for optional scalars (agent)](https://github.com/borco/rehuco/issues/101)

- **Common/plugin boundary — settled (#195)** — the [[field-schema#field-mapping]] tiers (common core / resource fields
  / per-type) were a first cut until the field toolkit and plugin blocks ([[plugins#overview]]) landed; they are now
  the declarations themselves, each plugin naming its own fields and the core naming the common ones
  ([[field-schema#resource-types]]). The generic editor still does not depend on it — an undeclared key falls back
  ([[plugins#fallback-editor]]), which is what lets the boundary move without losing a value.
- **Collection *type* — deferred** ([[field-schema#resource-types]]) — which fields a `type: Collection` record
  shows/edits, and whether it re-gains a **recomputed** member-stats cache. Decide when a real
  collection is in hand. *(The `collections` membership fields are settled, [[field-schema#sources]].)* Partially
  designed since: placement, discovered-vs-genuine, and entity authority are recorded in [[plugins#grouping-entities]];
  only the type's own field set still waits for a real collection.
- **Author entity plugin — deferred to the catalog-cache era** — aliases and per-store URLs as a metadata-only
  grouping-entity type ([[plugins#grouping-entities]], [[daz3d-personal-database#authors-urls]]), arriving with
  CacheDB's `.rehudb` (its browser/aggregation UI is what needs the cache); documents reference authors by
  credited name until then, and per-document `{name, url}` entries ([[field-schema#authors]]) fold into the entity
  when it lands.
- **Optional scalars read as `None` — done (#100 core, #101 display)** — absent is not `0`: the measured/claimed
  numerics (`original_size` / `current_size`, the three durations, `current_count`), `rating` (it may be negative, so
  `0` is a real rating and unrated must be `None`), and `released` read as `None` when absent; strings, lists, and the
  boolean flags keep their coercion defaults. Absent-on-disk ↔ `None`-in-code: JSON `null` is accepted on read but
  never written — setting `None` omits the key (the fixtures' `images_count: null`, renamed to `current_count` by the
  block chain's v4 step, normalizes away on save). Display
  follows: `None` renders empty, so a genuine `0` renders honestly (revises [[field-schema#duration-format]]'s old
  "`0` renders empty" rule).
- **Membership by identity** — `collections[].title` links to a series by name today; move to
  resource identity ([[data-model#stable-identity]]) once UUIDs are minted.
- **Per-user storage — resolved** ([[field-schema#per-user-shared]]): per-user keys nest under the plugin block's
  `users` map from block layout v1. Still open here: the catalog-cache-era **mass-rename** job (old username → new,
  across every file naming the user) and where a **public** learning path lives (below).
- **Learning-path visibility storage — resolved** ([[field-schema#learning-path-ownership]]): a public path
  is a **copy** into the reserved `public` scope, leaving the owner's entry untouched, so there is no
  un-publish and no question of where an un-shared path lands. Ownership is structural (who holds the full
  entry) rather than a recorded field. Still open around it: whether **publishing also mints the entity
  document** ([[plugins#grouping-entities]]'s materialize-at-publication sketch) or only copies the entry —
  two acts that want one sentence; and how two users' same-titled paths reconcile when one is published.
- **Identity collapse on import — undecided.** Imports file per-user state under `unknown` while the viewer
  shows the *current* identity, so a freshly converted resource shows none of its imported learning paths
  (or its rating) until the two usernames are set to the same value — which is explicitly supported. If
  that is the intended migration flow it should be said here; if it is not, "subscribe to the `unknown`
  identity's entries" becomes a third remedy alongside the mass-rename job (#108).
- **`default_tags` consolidation — deferred** ([[field-schema#boolean-flags]]) — a later revision may fold the
  fixed-vocabulary bools (`complete`/`online`/`viewed`/`todo`/`keep`) into one toggle-set list
  with a vocabulary from `.rehuco` (scope, labels/icons), migrated via a plugin-block
  `format_version` bump ([[data-model#schema-version]]). `favorite` stays separate. v1 keeps individual bools.
- **The image count on import — resolved (#198)** — a reference-images `.tc` imports with **neither** count
  written (the old `duration` is not assumed to be one). `current_count` is filled by counting the content
  zips' entries ([[data-model#resource-scoping]]), on an explicit action that fills a label beside the stored
  value rather than overwriting it: a stored count disagreeing with the archive is evidence of a refreshed
  zip, not a stale number to correct silently. `advertised_count` is hand-entered — nothing measures a claim.
- **Size on disk — resolved ([#223](https://github.com/borco/rehuco/issues/223),
  [#232](https://github.com/borco/rehuco/issues/232))** — `original_size` and
  `current_size` are measured over the shared content-file set
  ([[data-model#resource-scoping]]) and the shared exclusion list
  ([#226](https://github.com/borco/rehuco/issues/226)), so a file counted by the size scan can never be
  skipped by the checksums. Both rows run the **same** scan — *when* you press one is the whole difference
  — so they are **one field with one Measure and one measured readout**, and a copy button per row: one
  walk of the tree, two acceptances, each still explicit and separate (#232). It means
  `original_size`'s copy on a partly-deleted resource replaces the denominator of "how
  much is left" with the remainder. That is accepted rather than guarded: two independent rows are what
  let a re-downloaded resource have its original refreshed on purpose, and the alternative (tc4's rule,
  where only `current_size` computes and seeds `original_size` when empty) cannot express it. Still no
  `advertised_size` ([[field-schema#duration-size]]) — nothing publishes one.
- **Duration on disk — resolved ([#224](https://github.com/borco/rehuco/issues/224),
  [#233](https://github.com/borco/rehuco/issues/233))** — `original_duration` and `current_duration` are
  measured over the same content-file set and exclusion list the sizes use, so a video the size scan
  counted is a video the duration sums. The same *when you press it* caveat as the sizes applies, and is
  accepted for the same reason — and, as with the sizes, they are **one field with one Measure and one
  measured readout**, and a copy button per row (#233): one reading of the videos, two acceptances, each
  still explicit and separate. This pair is where the merge pays off most, since the scan behind it is the
  slow one — a container header read per video, or a subprocess per video with the external backend.
  `advertised_duration` deliberately keeps **no** row: it is the claim `original_duration` is checked
  against ([[field-schema#duration-size]]), and measuring it would erase the comparison.
  Reading a container is delegated to a **probe backend**, of which two ship, selected by an `engine`
  name the way the Markdown renderer's is
  (the `Videos` settings page is where one is selected, #225): **MediaInfo**, whose
  library is bundled with the app and is therefore the default, and **ffprobe**, an executable the user
  points at. A backend that cannot run *reports that* rather than measuring `0` — a silent zero is
  indistinguishable from a tutorial holding no video. The recognized video extensions are a list, not a
  constant, defaulting to tc4's set.
- **Measuring runs off the GUI thread — resolved (#223)** — every measure row (both sizes, both
  durations, and the content count) hands its measurement to a worker and is *busy* until it answers, so a multi-gigabyte tree on an
  SMB mount cannot freeze the window and a scan already running cannot be started again or half-applied.
  This is interim ownership: the task queue ([#201](https://github.com/borco/rehuco/issues/201)) and its
  dock ([#202](https://github.com/borco/rehuco/issues/202)) are where these belong, as jobs that can be
  watched, paused, resumed, cancelled and reordered alongside the checksum runs
  ([#204](https://github.com/borco/rehuco/issues/204)) — which also supersedes the single app-wide
  "the disk is busy" flag tc4 carried.
- **`created` / `updated` seeding — resolved** — both seed from the `.tc` file's **mtime** on import (ctime is
  unreliable cross-platform, and tc4 tracked no separate creation history) ([[field-schema#record-timestamps]]).
- **Description image resolution** — confirm sibling-relative path handling matches [[data-model#image-meanings]]'s
  screenshot model.
- **UUID ([[data-model#stable-identity]]) and per-block format version ([[data-model#schema-version]],
  [[plugins#plugin-blocks]])** — the UUID is minted **at creation** (`RehuDocument.new`, #141), not only at import,
  and each block's `format_version` is **stamped where the block is built** (#134); neither is present in a legacy
  `.tc`, so an import mints them like any other new document.
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
- The keys appear in **canonical save order** ([[field-schema#canonical-order]]): `core` then the active block lead,
  each led by its own leading keys and otherwise alphabetical; a `None`/absent field is omitted rather than written as
  `null`. Each fixture below was regenerated through a real `save()`, not hand-written.
- Values are illustrative; each example stresses the edge case named in its heading.

### Tutorial — multi-source, multi-collection, split duration, hidden screenshots, year-month date

```json
{
  "format_version": 2,
  "core": {
    "type": "tutorial",
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "created": "2026-01-15T09:30:00Z",
    "updated": "2026-06-20T14:12:00Z",
    "sources": [
      {
        "title": "Intro to Sculpting",
        "publisher": "Example Publisher",
        "url": "https://example.com/intro-sculpting",
        "primary": true
      },
      {
        "title": "Sculpting, Extended Cut",
        "publisher": "Second Platform",
        "url": "https://second.example/sculpting"
      }
    ],
    "advertised_tags": [
      "sculpting",
      "3d",
      "modeling"
    ],
    "authors": [
      "First Author",
      "Second Author"
    ],
    "current_size": 1073741824,
    "description": "# Intro to Sculpting\n\nCovers the basics; see `info01.jpg` for reference.",
    "extra_tags": [
      "rework"
    ],
    "hidden_images": [
      "info03.jpg",
      "info07.jpg"
    ],
    "original_size": 5368709120,
    "released": "2025-03"
  },
  "tutorial": {
    "format_version": 1,
    "advertised_duration": 72000,
    "collections": [
      {
        "title": "Sculpting Series",
        "index": 1,
        "url": "https://example.com/series"
      },
      {
        "title": "Bundle 2025",
        "index": 10
      }
    ],
    "complete": true,
    "current_duration": 18000,
    "level": [
      "intermediate"
    ],
    "online": true,
    "original_duration": 71220,
    "users": {
      "admin": {
        "favorite": true,
        "keep": false,
        "learning_paths": [
          {
            "title": "My Sculpting Path",
            "index": 2,
            "ref": 1
          }
        ],
        "rating": 4,
        "todo": false,
        "viewed": false
      }
    }
  }
}
```

### ReferenceImages — absent counts, no duration, full date, unrated

```json
{
  "format_version": 2,
  "core": {
    "type": "reference_images",
    "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
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
    "advertised_tags": [
      "reference",
      "anatomy"
    ],
    "authors": [
      "Third Author"
    ],
    "current_size": 2147483648,
    "description": "Anatomy reference images.",
    "extra_tags": [],
    "original_size": 2147483648,
    "released": "2024-11-08"
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
    "type": "collection",
    "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
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
    "advertised_tags": [
      "sculpting",
      "series"
    ],
    "authors": [
      "First Author"
    ],
    "description": "The full sculpting series.",
    "extra_tags": [],
    "released": "2025"
  }
}
```

## §17.8 Canonical serialization order

[[[field-schema#canonical-order]]]

A `.rehu` is JSON and JSON objects are unordered, so key order is a property of the **write**, not of the document:
`RehuDocument.__data` carries its keys in whatever order construction and the setters left them, and one canonical
top-to-bottom layout is imposed only at the single boundary that produces a file. Two documents with identical content
therefore serialize to identical bytes regardless of how their keys were built up in memory — a converted `.tc` and a
migrated v1 file included. The §17.7 fixtures are shown in exactly this order; each was regenerated through a real
`save()`. The contract (source of truth `rehuco_core.rehu_serialization` —
`ordered_for_file` / `ordered_block` / `ordered_users_map` — and `RehuDocument.save`):

- **Top level:** `format_version` (it describes the file), then `core`, then the **active** plugin block (the one this
  file's `type` names — the block a reader opening the file by hand looks for first, right after the core it belongs to),
  then every remaining top-level key **alphabetically** — inactive/unknown blocks and any stray key carried verbatim
  ([[plugins#plugin-blocks]]), sorted together rather than each getting a category.
- **Inside `core`:** a short list of **leading keys** — `type`, `id`, `created`, `updated`, `sources`, in that order
  (what a reader looks for first: what it is, which record, when it was made, and — via `sources` — what it is *called*)
  — then every other core key **alphabetically**. The list is deliberately short and needs no maintenance: a core field
  missing from it merely sorts with the rest, never misplaced.
- **Inside the active block:** its own `format_version` leads ([[plugins#plugin-blocks]]), then every other block key
  **alphabetically**. If the block carries a `users` map ([[field-schema#per-user-shared]]) it is ordered one level
  deeper: **usernames alphabetically, and each user's own fields alphabetically**.
- **Inactive/foreign blocks are carried through, never reordered** — a block this build does not own keeps its bytes
  ([[data-model#write-integrity]]); reordering would churn the file to reorganize fields the document cannot interpret.
  Only the active block and `core` are laid out; a retained block that is malformed (not an object) is passed through
  as-is rather than dropped.
- **Formatting:** `indent=2`, `ensure_ascii=False` (non-ASCII is written literally as UTF-8, not `\uXXXX`-escaped), and
  a **trailing newline**.
- **`null` is accepted on read, never written** ([[field-schema#deferred-items]]): JSON `null` reads as `None`/absent,
  but setting a field to `None` **omits the key** rather than writing `null` — so a value that normalizes to `None` on
  load (an absent optional scalar, an emptied `hidden_images`) is simply gone from the next save, and no `.rehu` this
  build writes ever contains `null`. A block made active *mid-session* is normalized on the switch rather than on load,
  so this holds of every block a document writes, not only the one it opened at ([[plugins#plugin-blocks]]).

Which blocks are written at all — the block persistence invariant, an inactive block dropped only once its type was
claimed then abandoned this session — is decided by `RehuDocument` and passed in, so this layer stays a pure function of
the payload ([[plugins#plugin-blocks]]).

## §17.9 Source-inspection docks

[[[field-schema#source-inspection-docks]]]

- [#111: feat: source viewer dock — read-only raw `.rehu` JSON, hidden by default](https://github.com/borco/rehuco/issues/111)

Two read-only inspection docks let a developer (or a curious user) see the serialization boundary directly. Both are
hidden by default, live in the document's own dock shell ([[plugins#dock-shell]]) alongside the viewer/editor surfaces,
and render monospaced, mouse-selectable text.

- **Save Preview** — the document's **live re-serialization**: byte-for-byte what a `save()` would write *now*,
  reflecting unsaved edits and the in-memory format upgrade a just-loaded older file received before any write
  ([[data-model#schema-version]]). It is produced by the **`serialize()` seam** — `RehuDocument.serialize()`, the one
  place a `.rehu`'s bytes are made, applying exactly the canonical order and formatting of [[field-schema#canonical-order]]
  — which `save()` itself also calls (`save()` *is* `serialize()` plus an atomic write), so the preview can never drift
  from what a save produces. The seam deliberately **never checks the lock state and never touches disk**, so even a
  locked or legacy-`.tc` document still previews what its save *would* emit. Two fields lag by design: a save stamps a
  fresh `updated` just before writing, and a first-ever write stamps `created`
  ([[field-schema#record-timestamps]]), so the preview shows the *stored* values, not the yet-to-be-minted stamps.
- **On Disk** — the **verbatim file bytes**, read straight off the document's path, unparsed. For a legacy `.tc`-backed
  document the path is the `.tc` itself, so this shows the original source; a never-saved draft shows a placeholder
  instead of a file.

The two **diverge exactly** on the states worth seeing: an unsaved edit (Save Preview moves, On Disk does not), and a
just-loaded older file the model upgraded in memory but has not written back — which is how the On Disk view surfaced the
v1 → v2 / per-user-map migration during development, a concrete read on [[data-model#write-integrity]]'s
upgrade-on-first-save boundary.

Their **refresh disciplines differ deliberately**, and that difference is the substance of the #152 fix. Save Preview
mirrors the live in-memory document, reacting to every field change — but **only while visible**: a change while hidden
merely flags the preview stale, and the deferred re-serialization runs on show, so a large document is never
re-serialized on every keystroke behind a hidden dock. On Disk watches only the **file-touching seams** — and never value
edits, keeping a large on-disk file off the per-keystroke path entirely.

Which signals *are* those seams is the substance of the #174 fix. Watching the properties that a file-touching operation
happens to move — `dirty`, `path`, `lock_reasons` — is not the same as watching the operation: a property notifies only
on an **actual change**, so reverting a *clean, unlocked* document moves none of them (`dirty` was already false, `path`
and `lock_reasons` reseed to equal values) and the dock kept showing pre-revert bytes — on exactly the out-of-band-edit
workflow Revert exists for. The seam therefore has its own **unconditional** signal, `reloaded`, raised by every
`revert()` and every successful `convert()`; the property subscriptions stay, covering the seams that are *only* a
property move (a save clearing `dirty`, a new save path).
