# Daz3D Personal Database — Predecessor Projects and Import Notes

[[[appendices.daz3d-personal-database]]]

## Overview

[[[appendices.daz3d-personal-database#overview]]]

Two predecessor projects (both listed in the repo README's History table) managed a personal catalog of
purchased Daz3D packages — zip archives as sold by DAZ and third-party stores — and are the direct ancestors
of rehuco's planned Daz3D plugin ([[plugins#daz3d-plugin]]):

| Project | Period | Commits | Stack | State |
| --- | --- | --- | --- | --- |
| [daz3d-personal-database](https://gitlab.com/iborco-software/daz3d/daz3d-personal-database) | 2022/01–2023/11 | 754 | PySide6 + QML, SQLAlchemy, poetry | feature-rich, abandoned |
| [daz3d-personal-database-2](https://gitlab.com/iborco-software/daz3d/daz3d-personal-database-2) | 2023/05–2023/09 | 1053 | PySide6 widgets + QtAds, SQLAlchemy, poetry | rewrite, stopped before feature parity |

This appendix records what each does, the data formats each produces and consumes, what (if anything) is
worth importing into rehuco, and what rehuco needs before it can import their data.

## 1. daz3d-personal-database (v1)

[[[appendices.daz3d-personal-database#v1]]]

A QML-fronted catalog of Daz3D package archives. Its pipeline:

- **Scan** configured folders for package zips (a `QThread` worker + job queue). For each zip it reads the
  DAZ Install Manager metadata bundled inside the archive — `Manifest.dsx` (file list, install actions) and
  `Supplement.dsx` (product name, install types, product tags), both small XML formats (samples in the
  repo's `examples/`).
- **Overlay** each zip with a user-editable YAML sidecar (`<zip-name>.dpdml`, next to the archive) holding
  everything the `.dsx` files don't: product name/URL, SKU, authors, requires/provides, figures,
  description, favorite flag, published date, tags. The overlay is the durable source of truth for user
  edits.
- **Cache** everything in a SQLite database (SQLAlchemy) for fast search/browse, including preview images
  extracted from the zips and stored as blobs. The DB is explicitly rebuildable from the archives +
  overlays (scan uses a mark-and-sweep `visited` flag to prune stale rows).
- **Scrape** product pages to fill overlay metadata: Selenium-driven (headless Firefox) scrapers for
  daz3d.com, Renderosity, Renderotica, RenderHub, ForeRender, and CGBytes.
- **Install** packages: a *copy installer* (drop the zip into DIM's downloads folder for DAZ Install
  Manager to handle) and an *extract installer* for non-DIM archives, which extracts into the library and
  records ownership so an uninstall is possible (see below).

### 1.1 v1 data formats

[[[appendices.daz3d-personal-database#v1-formats]]]

- **Config file** (YAML, path remembered via `QSettings`): `cache.path` (SQLite location), `folders:` (list
  of `{path: …}` archive folders), `dim_downloads_folder`, `my_library_folder`, `daz_folder`, plus cached
  image size/filter. Per-machine configuration, not catalog data.
- **`.dpdml` overlay** (YAML sidecar, one per archive, validated with `fastjsonschema`): `index`/`total`
  (multi-part archives), `product {name, url}`, `sku`, `authors [{name, url}]`, `requires [{name, url}]`,
  `provides [{name, url}]`, `figures [str]`, `description`, `favorite`, `published`, `tags [str]`.
  **This is the only v1 data worth importing** — everything else is derived.
- **SQLite cache DB**: tables `archive` (zip path/size/mtime, product fields, favorite, sku, description,
  raw `Manifest.dsx`/`Supplement.dsx` bytes, overlay mtime, scan bookkeeping), `image` (per-archive preview
  blobs with position), `author`, `figure`, `require`, `tag` (each many-to-many with `archive`), and a
  settings table for app state. Cache only — rebuildable, no unique data.
- **DAZ inputs** (consumed, not produced): `Manifest.dsx` and `Supplement.dsx` XML inside each package zip.
- **Extract-installer records**: per install, a `.dpd/$PUBLISHER/$FOLDER/$ARCHIVE.yaml` listing the files
  the archive contributed, plus a `.dpd` YAML map in every touched directory mapping each installed file to
  the archive(s) that own it (documented in the repo's `docs/extract-installer.md`).

## 2. daz3d-personal-database-2 (v2)

[[[appendices.daz3d-personal-database#v2]]]

A ground-up rewrite in PySide6 widgets with QtAds docks (DB browser, details, tags, settings, log, job
manager), started to escape v1's QML pain. It pivoted to a **project-file** model: instead of one global
config, the user opens a `.dpd` project describing root folders to scan, tag groups, and filter bookmarks;
a SQLite sidecar caches the scanned file tree.

It stopped before reaching v1's feature set: the DB models only the scanned file/folder tree with
thumbnails — no archive metadata, no `.dsx` parsing, no scrapers, and tags were never wired to files (tag
vocabularies exist only in the project file). Its real legacy is architectural: `simple_property`, dockable
tools, saveable dock layouts, a job manager, filters with history/bookmarks — patterns that flowed through
tutcatalog5/resource-hub into today's `borco-pyside`/`rehuco-agent`.

### 2.1 v2 data formats

[[[appendices.daz3d-personal-database#v2-formats]]]

- **`.dpd` project file** (YAML, `strictyaml`-validated): `root_folders [str]` (relative paths allowed),
  `tags` — groups of `{name, textColor, backgroundColor, items [str]}` (ARGB hex colors), and
  `filters_bookmarks` — named saved filters (`{name, folders [str], ordering, orderingDirection}`).
- **SQLite sidecar** (`<project>.dpd.db`, next to the project file): a single self-referential `file` table
  (parent/children tree; `is_root`, `is_dir`, `path`, `name`, `size`, `created`, `modified`, `thumbnail`
  blob). Pure scan cache — rebuildable, no unique data.

## 3. Worth importing into rehuco

[[[appendices.daz3d-personal-database#worth-importing]]]

**Code: almost nothing directly.** The generic patterns both projects pioneered already live on, rewritten
to current conventions, in `borco-pyside` and `rehuco-agent` (properties, docks, layouts, settings,
logging). The pieces with no rehuco equivalent yet, worth mining when the Daz3D plugin work starts:

- **`.dsx` parsing** — v1's `Manifest.dsx`/`Supplement.dsx` readers and the sample files in `examples/`.
- **Extract-installer design** — the per-directory ownership-map scheme is a worked design for
  install/uninstall with tracked side effects, exactly the custom-action shape [[plugins#daz3d-plugin]]
  calls for. The recording format would change; the file-ownership bookkeeping idea carries.
- **Store scrapers** — the six Selenium scrapers encode per-store page structure; likely bit-rotted, but a
  reference for which fields each store exposes. The LLM-based URL extraction planned in
  [[acquisition-tooling#llm-url-extract]] is the more maintainable successor.
- **v1's field vocabulary** — `sku`, `figures`, `requires`/`provides` (name+URL pairs) is a
  field-tested schema for the Daz3D plugin block, distilled from ~2 years of real cataloging.

**Data: the v1 `.dpdml` overlays.** One YAML file per archive, sitting next to it, holding all user-entered
and scraped metadata. The v2 `.dpd` project files carry only folder lists and tag vocabularies (the colored
tag groups may inform tag presentation, but there are no per-item assignments to migrate). Neither SQLite
database needs importing — both are declared caches, rebuildable from files.

## 4. What rehuco needs to import their data

[[[appendices.daz3d-personal-database#import-needs]]]

Daz3D support is deliberately parked past milestone C ([[implementation-plan]] scope), so this is a
recorded shopping list, not near-term work:

1. **The Daz3D plugin** ([[plugins#daz3d-plugin]]) — a `daz3d:` plugin block to receive the type-specific
   fields: `sku`, `figures`, `requires`, `provides`, install-state tracking per user/box.
2. **Author URLs — options recorded, decision deferred** ([[appendices.daz3d-personal-database#authors-urls]]);
   how URLs relate to the core `authors` name list is chosen during plugin work, enabled by the hook seam.
   `requires`/`provides` (also `{name, url}` lists) live wholly in the block; only their editor is new work.
3. **A `.dpdml → .rehu` importer** — same shape as the `.tc` migration
   ([[acquisition-tooling#tc-to-rehu]]): walk archive folders, pair each zip with its `.dpdml`, and emit a
   `.rehu` document per product. Field mapping is direct: `product.name` → title, `product.url` → sources,
   `authors` names → common `authors` (URL handling per [[appendices.daz3d-personal-database#authors-urls]]),
   `description`/`tags`/`favorite`/
   `published` → common core, the rest → the `daz3d:` block. Multi-part (`index`/`total`) packages become
   **one document per product** via the multi-file manifest ([[appendices.daz3d-personal-database#multi-part]]).
4. **Preview image extraction** — v1 pulled preview images out of the zips into its DB; rehuco's importer
   must extract them next to the `.rehu` document instead (images live as files, not blobs).
5. **`.dsx` readers** — parse `Manifest.dsx`/`Supplement.dsx` from the zip to seed documents that have no
   overlay, and to power the eventual install action.

## 5. Decisions

[[[appendices.daz3d-personal-database#decisions]]]

Two import-mapping questions raised above were worked through in discussion (2026-07): multi-part grouping
is settled; author-URL storage is narrowed to options, to be decided during the Daz3D plugin work.

### 5.1 Author URLs: options, not a decision

[[[appendices.daz3d-personal-database#authors-urls]]]

How author URLs relate to the core `authors` name list ([[field-schema#field-mapping]]) is **deliberately
left open**: the options below are recorded for when the Daz3D plugin work starts, and the choice is
enabled — not forced — by the settled architecture in the first bullet:

- **Settled: the enabling architecture.** Plugins get a non-GUI core layer loaded by agent and node alike
  (plugins own web rendering, so a node-side layer exists anyway), plus a core-field-change hook seam in
  `rehuco-core` so a plugin can observe core-field edits — a plugin-contract extension not yet written into
  [[plugins#core-vs-plugin]]. Cross-block consistency stays best-effort with self-healing repair across
  sync merges (resolved per sub-block, [[sync#overview]]) and plugin-less writers — true under every
  option below that keeps URLs outside the core field.
- **Option: decouple — a name-keyed URL map in the `daz3d:` block.** Core untouched, text-list editing
  intact; the plugin syncs the map via the hook seam. A rename *detaches* its URL — visible, recoverable.
  (An index-keyed map is off the table: shape edits silently reattach URLs to the *wrong* authors.)
- **Option: duplicate — the block carries its own `authors: [{name, url}]` list.** Self-contained and
  merge-friendly as a unit, but two lists can drift; the plugin reconciles the block list against the
  core names.
- **Option: promote — core `authors` items become `{name, url}` records** behind a tolerant reader (plain
  strings stay legal; the record form is written only for entries with a URL). No cross-block invariant at
  all — at the cost of a record-list editor (shared with `sources`, [[field-schema#sources]]) and a change
  to the `authors` row in [[field-schema#field-mapping]]. Any block-side maps fold into it later.

### 5.2 Multi-part archives: one document per product

[[[appendices.daz3d-personal-database#multi-part]]]

v1's `index`/`total` (one product sold as several zips) maps to **one `.rehu` per product**, not one per
part: a purchase is one resource, and per-part documents would split tags/description/favorite across
copies. The vehicle is the **multi-file manifest block** that file-scoped `.rehu` already requires for
exactly this case ([[data-model#resource-scoping]]: naming convention alone can't bind `foo.zip` +
`bar.zip` into one resource). The importer merges the per-part `.dpdml` overlays into the one document and
lists every member zip in the manifest. That block is acknowledged in the data model but not yet
specified — specifying it gates the importer for multi-part packages only; single-part packages (the vast
majority) don't wait for it.
