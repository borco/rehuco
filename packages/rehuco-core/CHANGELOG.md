# Changelog

All notable changes to `rehuco-core` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-core` only, and its releases are tagged `rehuco-core-X.Y.Z`.

## [Unreleased]

### Added

- The `.rehudb` catalog cache (`CatalogCache`): a SQLite file per `.rehuco`, named by its rehuco id inside a
  cache folder the caller names. It holds the roots, keyed by their ids, and one row per record found under
  them: the common core a browser shows, the authors, tags and publishers, and the record's size,
  modification time and content hash. It also holds the type-specific fields: a tutorial's three durations and
  its levels, and a reference pack's claimed and measured image counts. `catalog_type_fields` names the ones a
  type contributes, and a scan fills only those. The schema is versioned through `PRAGMA user_version` and upgraded
  forward only. A cache newer than the build, or a file that is not a database, is discarded and rebuilt.
  Reconciling against a `.rehuco` keeps a relabeled or re-pointed root's rows. Removing a root deletes its
  rows and frees their space. Rows can be read whole or narrowed by free text and `folder`, `authors`,
  `tags`, `publishers` and `type` tokens.
- A full scan of one root (`CatalogRootScan`, queued as `ScanCatalogRootJob`), and root removal as
  `RemoveCatalogRootJob`. The scan reads every `.rehu`, and every `.tc` no same-stem `.rehu` sits beside. A
  record that will not read keeps a row naming why. A root that does not list keeps its rows; a scan whose
  root went away before it finished is not applied. Each listing and each record read is held under the
  rename coordinator, so a rename waits for one read rather than the scan.
- The root scan is incremental: given the root's cached rows (`CatalogCache.signatures`), it opens only the
  records whose modification time or size changed, plus any row that could not be read before. Unchanged records
  keep their rows, and what was not found is removed. The scan job reports progress against the previous scan's
  row count. It still lists every folder, so a record nested inside a tutorial is found like any other.
- Single-record cache updates between scans. `CatalogRecordUpdater.upsert` re-reads one record after a save or a
  conversion, and a converted `.rehu` takes over its `.tc`'s row. `CatalogRecordUpdater.verify` re-reads a record
  whose file no longer matches its row. `CatalogCache.remove` drops a deleted record's row. `CatalogCache.apply_relocation`
  applies a rename's executed plan (`RehuRenamer.executed`) without reading anything: a renamed folder rebases every
  row beneath it, a file-scoped rename only its own. A record missing under an offline root keeps its row.
- `CatalogScanner.walk()` yields one listing at a time. Given a coordinator, it lists each directory under
  its hold and follows a folder renamed mid-walk. It can also collect uncovered `.tc` records.
- The `.rehuco` file (`RehucoFile`): a rehuco id and an ordered list of folder roots, each with a stable id, a
  label and a removable flag. Roots are added (a duplicate folder is refused, compared case-insensitively where
  paths are), removed, relabeled and moved to the top, up, down or bottom. A label defaults to the folder's
  name, numbered on a clash (`foo (2)`). Saves are atomic, unknown keys are kept, and a file newer than the
  build opens read-only.
- A reference pack's content images include its loose images as well as its archive members: whatever
  images are among the files the content walk gives the record. A loose image is keyed by size and
  modification time. Archives and folders of loose images sort together, case-insensitively, with the
  pack's own folder first. The enumeration takes the excluded-files globs the checksums take, so the two
  agree on every file.

### Changed

- An image named by a legacy screenshot pattern (`01.jpg`, `cover.jpg`, `sample-01.jpg`, ...) is content
  in every folder: enumerated, checksummed and measured like any other file. Only a `<record>NN` image
  beside its record is a screenshot sidecar. A `.checksum` written before this lacks such files, and the
  next verify adopts them as unexpected.
- Converting a `.tc` measures `current_size` after renaming its screenshots, so the size never counts the
  images the conversion itself claims.

### Removed

- The `screenshot_name_patterns` parameter of the content walk, the checksum runs, jobs and seeding, the
  directory classifier, size on disk and video duration: the patterns no longer decide what is content.
  Checksum, sweep and manifest jobs no longer save them in their state; an older saved state still loads.

## [0.2.0] - 2026-09-27

### Added

- Checksums — a `.checksum` record beside the `.rehu` with five algorithms, generate/verify that skip
  recently checked files, a resumable folder sweep, adoption of legacy `.sfv`/`.md5`/`.sha*` manifests,
  and per-location trust.
- Content enumeration — which files a resource covers (exclusive between nested records), the images
  inside a reference pack's archives, and measured size on disk and video duration.
- Per-type field schemas declared by each plugin.
- A task-queue engine: one job at a time, pause/cancel/reorder, optional persistence, per-job log scope.
- A rename barrier (`RenameCoordinator`) that makes running jobs and open archives stand aside for a
  rename.
- Bulk `.tc` migration: a dry-run plan over a folder tree, conversion with `.orig` backups, and discarding
  them.
- Screenshot naming patterns as a configurable regex list, and on-disk move/delete/convert of screenshots.
- A `Deleter` protocol for choosing how files are removed (e.g. to the Recycle Bin).
- Record-list editing helpers for authors, collections and learning paths.

### Changed

- Converting a `.tc` keeps each screenshot's own number instead of inferring its slot.

### Fixed

- A malformed `core.type`, or a required string field holding JSON `null`, locks the document instead of
  reading as the text `"None"`.
- A typeless document's empty block key is no longer treated as an active block.
- Switching a document's type normalizes the block being activated.
- `created` is stamped when a `.rehu` is first written.
- `.rehu`/`.tc` parsing enforces size, depth and entry-count limits.
- An unparseable legacy duration no longer imports as `0`.
- `info.tc` is treated as directory-scoped, like `info.rehu`.

## [0.1.0] - 2026-07-29

The first version carrying the library itself: `0.0.0` and `0.0.1` were name-reservation stubs built
outside this repository, so everything below is new rather than changed.

### Added

- `.rehu` documents — a model whose JSON read/write preserves unknown fields across a round-trip, plus
  the format definition, serialization, screenshots, and rename support.
- Lock derivation — why a parsed document is read-only, and the field-value coercion that goes with it.
- A migration runner and the migration chains for tutorials, reference images, and the `.rehu` core
  block, with the steps shared between them factored out.
- A plugin registry — the plugins a build ships, and an immutable index over them.
- Legacy `.tc` support — document and screenshot reading, description handling, and conversion to
  `.rehu`.
- Collection and learning-path entries, a titled index, and the shared constants.

## [0.0.1] - 2026-06-30

Second name-reservation stub on PyPI, published a day after `0.0.0` and still carrying no library code.

## [0.0.0] - 2026-06-29

Name-reservation stub, published to PyPI so the name could not be taken by anyone else. Neither this
release nor `0.0.1` was built from this repository — when both were uploaded the repository contained no
Python packages at all, so there is no source in the history that corresponds to them.
