# Changelog

All notable changes to `rehuco-core` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Changelogs are per package in this monorepo, matching the per-package release tags: this file covers
`rehuco-core` only, and its releases are tagged `rehuco-core-X.Y.Z`.

## [Unreleased]

### Added

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
