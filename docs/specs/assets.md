# §19. Assets: Store Libraries as Records

[[[assets]]]

## Overview

[[[assets#overview]]]

- [#673: docs: the asset type, the library wizard and prefix buckets](https://github.com/borco/rehuco/issues/673)
- [#674: feat(core): declare the asset type and its block](https://github.com/borco/rehuco/issues/674)
- [#675: feat(core): a source's site_id, and finding a record by site and id](https://github.com/borco/rehuco/issues/675)
- [#676: feat(core): asset columns and a formats link table in the cache](https://github.com/borco/rehuco/issues/676)
- [#677: feat(core): the .rehuterms license sidecar](https://github.com/borco/rehuco/issues/677)
- [#678: feat(agent): asset fields in the editor, the browser and the settings](https://github.com/borco/rehuco/issues/678)
- [#679: feat(agent): Open in Web Browser on the browser's selection](https://github.com/borco/rehuco/issues/679)
- [#688: feat(agent): the license subdock, Refresh License, and the sidecar's path in Copy as JSON](https://github.com/borco/rehuco/issues/688)

**Only the block, the cache and the license sidecar are built** (#674, #676, #677): `asset` is a declared type whose
fields are read and checked as §19.1 says and kept in the catalog cache, one column each and `formats` in a link table
of its own; no editor, browser column, filter or scan uses them yet. The rest is the design for this fourth resource type: something
acquired from a store to be used in other work, such as a 3D model, a texture set, an animation pack, an audio pack, a
Blender add-on or an Unreal plugin. It answers the *3D objects as a resource category* question
[[appendices.open-questions#still-open]] left open.

- **What it is for.** A store library of a few thousand items, most of them never downloaded, that has to answer three
  questions fast: *what do I own*, *can I use it in this project* (format, engine version, license) and *where is it*.
- **A record is mostly metadata.** One `.rehu` and a few screenshots per item; the files themselves arrive later, for
  the few items actually used ([[assets#online-only]]).
- **Records are created by a scan of the store account**, not by hand: the library wizard
  ([[acquisition-tooling#library-wizard]]) reads what the account owns and writes one record per item.
- **A library is thousands of small files in one root**, so such a root spreads them over prefix buckets
  ([[mounts-and-storage#buckets]]).
- **Daz3D is the same type with more on it** ([[assets#install]]), not a type beside it.

## §19.1 The `asset` block

[[[assets#block]]]

**Every field is optional, and a missing field means *not known*.** A plugin has no triangle count and a scan of a
store page measures nothing; neither is an error, and neither writes a zero. The block follows the rules every plugin
block does ([[plugins#plugin-blocks]]).

| Key | Value type | Filled by | Meaning |
| --- | --- | --- | --- |
| `kind` | one of [[assets#kind]] | scan, or by hand | what the item is; `unknown` until something says |
| `license` | string | scan | a license's short id ([[assets#licenses]]): `fab-standard`, `cc-by-4.0`, `fab-ue-only` |
| `license_url` | string | scan | where the store states the terms for this item |
| `formats` | string list | scan | file formats delivered: `fbx`, `glb`, `blend`, `uasset` |
| `compatibility` | map, string to string | scan | what it works with and in which versions: `{"blender": ">=4,<5", "unreal": "5.1-5.6"}` |
| `source_updated` | partial-precision date | scan | when the store last changed the item |
| `advertised_version` | string | scan | the version the store offers |
| `current_version` | string | by hand, or an install manager | the version of the local files |
| `advertised_size` | size (bytes) | scan | the download size the store states |
| `advertised_triangles` | range text | scan | the triangle count the store states, per format ([[assets#ranges]]) |
| `advertised_texture_size` | range text | scan | the longest side of the largest texture the store states ([[assets#ranges]]) |
| `triangles` | integer | measured | triangle count of the heaviest mesh at full detail |
| `texture_size` | integer | measured | longest side, in pixels, of its largest texture |
| `acquired` | UTC time, or a partial-precision date | scan | when the account got it, where the store says |

- **Reused from the core, not repeated in the table:** `description`, `released` (the store's publication date),
  `authors`, the tag lists, the screenshots, and the measured size pair ([[field-schema#duration-size]]).
- **Taken from the set tutorials and reference images share:** `rating`, `favorite`, `online` ([[assets#online-only]])
  and `collections` (a store bundle is a collection). `complete`, `keep` and `learning_paths` are left out: they
  describe content being studied, and an asset is not.
- **`source_updated` is not `updated`.** The core's `updated` is when the *record* was last edited
  ([[field-schema#resource-types]]); a store changing its item is a fact about the item.
- **`advertised_size` exists here and nowhere else.** [[field-schema#duration-size]] has none because no site
  publishes a tutorial's size. Stores do publish an asset's, and for a record with no files it is the only size there
  is: it is what a download is planned with.
- **The version pair is the size pair's shape:** what the store offers beside what is on disk. An item whose two
  versions differ has an update waiting.
- **The advertised counts are what the store states, as text** ([[assets#ranges]]); the **measured** ones are
  filled after a download, by hand until something measures them, and the scan never guesses them.
  The measured fields are `triangles` and `texture_size`. `triangles` is the heaviest single mesh because a pack's total says nothing
  about what one object costs to draw.
- **`acquired` is never asked for.** Where the store shows the date the scan records it; where it does not, the field
  stays empty. Fab states it for every owned item (the entitlement's `createdAt`). It sorts the library, and beside
  the date a license was read ([[assets#licenses]]) it says how far the saved terms are from the day the item was got.
- **`acquired` is a time where the store gives one**, unlike `released`, the core's publication date: an ISO 8601 UTC
  time with six fractional digits and a `Z` (Fab's `createdAt` to the microsecond: `2024-05-03T12:34:56.789123Z`),
  a partial-precision date (`2024-05-03`) where the store gives only a day. Never a local offset, so its text sorts
  in time order and the cache compares it as text; the library scan's cursor is the newest one
  ([[acquisition-tooling#library-scan-job]]).
- **`formats` is a field, not tags**, because it is the filter used most and the tag lists are the store's own
  vocabulary. The cache gives it a link table of its own, as tags have.
- **What the store calls its categories goes into `advertised_tags` untouched**, as every scraped tag does
  ([[acquisition-tooling#scraper-protocols]]).
- **What the scan makes from a store's field, rather than copies from its tag list, is a tag too, always prefixed
  by what it is**, because a store's own tags describe what is depicted and a bare word collides with them (a
  *mature* wolf, a *windows* prop). As tags, two spellings of one label merge the way any tag does, where fields
  would each need a merge of their own. The separator is `-`, never `:`, which the search line reads as a field
  token. From Fab:
  - `rating-mature` where the listing is `isMature`;
  - `platform-<name>`, lower-cased, for each of an Unreal format's `targetPlatforms` (`platform-windows`,
    `platform-mac`); none means any;
  - `ai-forbidden` where the listing is `isAiForbidden`, Fab's *NoAI* mark: no generative-AI datasets, development
    or training under a Standard License, as the item was tagged when it was got. It does not bar using AI tools on
    the file ([[appendices.assets#ai-tags]]);
  - `ai-generated` where the listing is `isAiGenerated`, Fab's *CreatedWithAI* mark.
- **A delisted item**, written without its listing, carries none of these.
- **A rig and levels of detail are the user's tags** (`extra_tags`). Fab states them per format and mostly leaves
  them empty, so the scan writes nothing for them.
- **What an item needs or supplies is not here.** No Fab listing states it; Daz3D's products do, and its design adds
  `requires` / `provides` when it is made ([[assets#install]]).

### §19.1.1 A count the store states as a range

[[[assets#ranges]]]

A store gives some figures as a band: Fab's triangle count of a format is `[12, 13)`, a texture's longest side
`[1024, 2049)`. `advertised_triangles` and `advertised_texture_size` keep them as **text a person reads at a
glance and types by hand**, inclusive at both ends: a value alone (`12`), a band (`1000-4999`), several values or
bands apart as a comma list, ascending (`1024,2048`, `12,40-60`), written and read only by
`rehuco_core.ValueRange`. A count the store states no range for, or one with nothing inside it, is left out.
A text typed that is no range stays as it was typed: it never locks the document, and a search finds nothing in it.

**A search compares by the bounds** (#678's): `triangles < 15` finds a record when **any** value of its range is
below 15, so `14`, `12-13`, `1-14` and `10-20` all match; `> 15` finds one whose largest value is above it. The
cache keeps the two bounds of each field in columns of their own, so the comparison is an integer one.

### §19.1.2 `kind`

[[[assets#kind]]]

One value from a closed list: `model`, `pack`, `character`, `animation`, `material`, `texture`, `decal`, `brush`,
`hdri`, `audio`, `vfx`, `plugin`, `tool`, `template`, `unknown`.

- A `pack` is many models sold as one item: an environment, a kit, a prop set.
- A `decal` is a texture projected onto a surface: cracks, stains, road markings. A `brush` is a sculpting or painting
  brush, or an alpha. Fab lists both as categories of their own.
- A missing `kind` reads as not known. The kind filter still finds such a record both as `unknown` and as an empty
  kind, so the unsorted items are one filter away whichever way they came to be.
- A MetaHuman is a `character`. A Blender add-on or an Unreal code plugin is a `plugin`; a standalone program is a
  `tool`; a sample project is a `template`.
- **`unknown` is a real value, not a missing one.** A scan that cannot classify an item writes `unknown`, so the items
  nobody has sorted are one filter away. It is the one field of the block that is never left empty.
- A site's scan maps the store's own listing type to a kind where the store states one, and writes `unknown`
  otherwise. It does not infer a kind from a title.

### §19.1.3 A record keeps its license text

[[[assets#licenses]]]

The terms are what decides whether an item can ship, and they are the store's to change or to take down. So **a
record keeps the text itself, in a sidecar beside it**: `<stem>.rehuterms`, one per record, never shared between
records. `license` in the block stays the short id a library is filtered by, and `license_url` where the store states
the terms.

- **The file is a YAML header and the terms as Markdown.** The header, between `---` lines, holds `title`, `url`
  (where the text was read) and `read`, the date it was read: a store's terms change, and a saved text is only as good
  as its date. A file with no `url` has no `url` key. It is read and written by `rehuco_core.license_terms`, an atomic
  write as a `.rehu` gets, under the record's own lock, and a file that cannot be read is refused, never taken for
  empty terms.
- **It is bookkeeping, not content.** Named by its suffix alone, `<stem>.rehuterms` is left out of a record's content,
  size and checksums as a screenshot and a `.rehuser` are, so a scan writing it or a refresh replacing it never makes a
  checksum stale, and a move never refuses a record for it. The Files list shows it as the record's *license*.
- **It belongs to the record as its screenshots and its `.rehuser` do.** A rename, a move and a delete carry it, and a
  record moved by hand takes it along with the rest of its files. A root that is offline takes nothing from another
  root's records, and a store that has gone leaves every text where it was.
- **The scan writes it with a new record** ([[acquisition-tooling#library-scan-job]]), reading each distinct license
  once per run, keyed by the store's license **path** rather than by `license_url`, which differs between labels of
  one license and may be empty (below). The text is therefore the terms on the day of the scan, which for an item got years
  earlier is not the day it was got; `acquired` beside `read` shows the gap, and nothing recovers the older text.
- **What Fab gives** (#686): each owned item names its license(s) as a `group` (`name`, `slug`, `url`) and a `path`
  (`license/standard/reference-plus-source`, `license/cc/cc-by`, `license/legacy/uem`). **The `path` is the stable
  identifier** and the short id is derived from it; the label is not (*Creative Commons* and *Creative Commons
  Attribution (CC BY 4.0)* are both `license/cc/cc-by`, and their URLs differ: a generic index page, and the license's
  own page). *Standard License* links to `/eula`, whose full text is public JSON at `/i/eula/fab_eula`; the CC pages
  read logged out; *UE Marketplace* has no URL, so its record has a `license` and no text. An item may hold several
  licenses (a Personal and a UEFN *reference only* tier; 241 of 4,250), and three delisted items hold none.
- **A file with no `url` is terms written for that item alone.** It is typed in, and nothing ever refreshes it.
- **It is read and edited in a subdock of its own**, as the description is, since the text can be long.
- **Nothing reads a license from the net when a record is opened.** A saved text changes only through *Refresh
  License*, on the browser dock's selection: each distinct URL among the selected records is read once and compared
  with what each record holds.
- **A refresh never replaces a text unasked.** A record with none gets one. Where the terms differ, the user is shown
  the license, both dates and how many records hold the older text, and it is replaced only on a yes. The text an item
  was got under may be the one that still applies to it, so it is not the tool's to overwrite.
- **A restriction is a different license, never a note.** Content a store limits to one engine gets an id of its own
  (`fab-ue-only`) so the limit is a filter, not a sentence in a description.
- ***Copy as JSON* names the file.** Each asset that has one carries its sidecar's path, so whatever reads the
  selection can read the terms.

Why the text is kept, and when a license binds the buyer, is [[appendices.assets#acquisition]].

A few thousand copies of two or three texts is the price, and it is paid on purpose: one shared copy per root, a
cache, or a license record of its own each leave some record without its terms the day a root is offline, a file is
moved by hand, or a store is gone.

### §19.1.4 A source carries the store's id

[[[assets#site-id]]]

`sources[]` ([[field-schema#sources]]) gains one optional key, **`site_id`**: the store's own identifier for the item,
a listing id or a SKU. It is a core field because any type's source can have one, though only the library scan needs
it.

- **It is the match key for a rescan.** A store renames items and serves one item under several URLs; the id is the
  one thing that stays.
- **The cache indexes `(site, site_id)`**, where the site is the source's `publisher`, which a scraper fills with
  its `site_name` ([[acquisition-tooling#scraper-registry]]), compared ignoring case, so finding the record for a
  listing is one lookup and never a walk. A source has no site key of its own: a publisher edited by hand stops the
  match.
- **An item owned on two stores is one record with two sources**, each with its own id, as a tutorial sold on two
  platforms already is.

## §19.2 A record without its files

[[[assets#online-only]]]

**Most asset records hold no content, and that needs no field.** The measured `current_size` already says it: empty or
zero means nothing is local, a value means the files are there. This is the reading [[field-schema#online-flag]]
already gives a tutorial kept as a `.rehu`, its screenshots and a URL, and it closes the *online-only and mixed
local/online resources* question for this type.

- **`online`** keeps its meaning: the item can still be had from its source. A rescan that no longer finds an item in
  the account sets it false and changes nothing else; **a scan never deletes a record**.
- **Downloading is not this type's business.** Files reach a record's place by whatever means the store offers; the
  next size measurement finds them.

## §19.3 Using an asset, and installing one

[[[assets#install]]]

**There is no install action for assets in general**, because there is no one thing to do: a store's launcher adds its
packs to a project, a Blender add-on installs through Blender, and a loose model goes through whatever import pipeline
the project has. Unlike Daz3D ([[plugins#daz3d-plugin]]), where installing is registering with one application, none
of that is rehuco's to drive.

- **What the browser offers instead is *Open in Web Browser*** on the selected records, beside *Copy as Path* and
  *Copy as JSON*: each record's primary source URL, opened in the user's everyday browser. From there the store's own
  page does the rest.
- **A site may bring its own install manager later.** Daz3D is the first, and the per-user, per-machine `installed`
  field [[data-model]] reserves for it belongs to that manager's block, as does `current_version` when a manager sets
  it. A store that turns out to be worth the same treatment gets the same shape.
- **Daz3D is therefore `asset` plus a manager**: its `sku` is a `site_id`, and the `requires`/`provides` its
  products state are fields its design adds to this block. It is not a second type with a second set of columns.

## §19.4 What adding the type touches

[[[assets#new-type-touches]]]

The first type added since the original three, so the places that enumerate types are listed once, here, for whoever
adds the next.

- **`rehuco-core`:** the field tuples and `BUILTIN_PLUGINS` in `plugins/plugin_registry.py`, and the exports beside
  it; `BLOCK_TARGETS` and a migrations subpackage once the block's shape first changes (`asset` has neither yet: a
  block with no chain is version 0); the per-key value rules in `rehu_locks.py`, checked only where the type
  declares the key; the typed getters on `rehu_document.py`; `TYPE_FIELD_COLUMNS` (with `COLUMN_FIELDS` for a column
  named apart from its field, as `asset_kind` is), the column DDL and a schema step in `rehudb.py` and
  `migrations/rehudb/`, with the formats link table; `rehudb_scan.py`, which fills them; `PLUGIN_PLACEHOLDERS` in
  `location_pattern.py`; and, for a type with a sidecar of its own as this one has ([[assets#licenses]]), whatever
  enumerates a record's files.
- **`rehuco-agent`:** the field-to-widget map in `documents/document_fields.py`; `TYPE_DOCK_NAMES`; the browser's
  columns and presets; the root layouts editor; the per-type settings pages and location templates; `type_label`;
  `SCRAPED_FIELD_NAMES` and the scrape result schema.
- **Specs:** the badge table in [[plugins#badge-colors]] and the mapping table in [[field-schema#resource-types]].

## §19.5 Deferral

[[[assets#deferral]]]

- **Measuring** `triangles` and `texture_size` from downloaded files. Until then they are typed in.
- **Install managers**, Daz3D's included ([[assets#install]]).
- **Licenses as something to browse.** A branch of the Tag Browser ([[plugins#tag-browser]]) listing the license ids
  in use, and a document per license, wait until someone wants more than the filter.
- **Any store beyond the first.** The wizard's protocol ([[acquisition-tooling#library-wizard]]) is what a second one
  is written against; none is designed here.
